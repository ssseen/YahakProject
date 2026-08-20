"""
3단계: 문제 유형 분류. Pinecone 유사 문제 검색으로 대분류/중분류(category_large/category_mid)를
채운다.

[설계 판단 - 과목(subject)은 여기서 정하지 않는다]
Pinecone은 "분류기"가 아니라 "유사 문제 검색기"다. 돌아오는 hit의 subject/category는
검색어와 비슷하게 생긴 "다른 문제"의 값이지, 지금 이 문제의 값이 아니다. 과목이 틀리면
pipeline.py가 엉뚱한 분기로 새서 (예: 영어 문제가 국사과 해설로 감) 지문 토큰화/보기 분리가
통째로 건너뛰어지는데, 이게 에러 없이 화면만 조용히 깨지는 형태라 추적이 제일 어렵다.
그래서 과목은 이미지를 직접 보는 1차 호출(problem_extractor.py)이 판단한 값을 그대로
쓰고, Pinecone 검색 결과의 subject는 아예 참조하지 않는다 (filter 조건으로만 사용).
"""
import os

from dotenv import load_dotenv
from pinecone import Pinecone

load_dotenv()

_INDEX_NAME = "geondi-questions"
_NAMESPACE = "questions"
_TOP_K = 3

# 코사인 유사도 임계값(1에 가까울수록 유사). 이 밑이면 "비슷한 문제를 못 찾은 것"으로 보고
# 미분류 처리한다 - 임계값을 낮게 잡아서 낮은 유사도의 hit를 신뢰하면, 잘못된 대분류/중분류를
# 확신을 갖고 사용자에게 보여주게 된다. 반대로 미분류로 빠지는 건 비용이 작다 (해설 자체는
# 정상 진행되고 카테고리 라벨만 "미분류"로 나옴). 그래서 보수적으로(높게) 잡았다.
# 0.75로 시작했으나 실제 인덱스(사회 과목, 18문항)로 검증한 결과 0.69~0.74 사이 점수의
# hit들도 카테고리가 맞아 보여서(예: 기후/생활양식 문제가 0.69로 미분류 처리됨) 0.7로
# 낮췄다 - 여전히 경험적 추정치라 다른 과목/더 큰 샘플로 계속 검증할 것 (아래
# _search_category의 경고 로그에 실제 점수가 남는다).
_SIMILARITY_THRESHOLD = 0.7

_UNCLASSIFIED = {"과목": "미분류", "대분류": "미분류", "중분류": "미분류"}

_pinecone_index = None


def _get_index():
    """Pinecone Index 클라이언트를 lazy하게 생성해 캐싱한다 (gemini_config.get_model과 동일 패턴)."""
    global _pinecone_index
    if _pinecone_index is None:
        api_key = os.getenv("PINECONE_API_KEY")
        if not api_key:
            raise RuntimeError("PINECONE_API_KEY가 .env에 설정되지 않음")
        _pinecone_index = Pinecone(api_key=api_key).Index(_INDEX_NAME)
    return _pinecone_index


def _extract_hits(results):
    """
    index.search()의 반환 shape이 SDK 버전에 따라 속성 접근(results.result.hits) 또는
    dict 접근(results["result"]["hits"])으로 다를 수 있어 방어적으로 꺼낸다.
    형태가 안 맞으면 빈 리스트를 반환한다 (호출부의 "hits 없음" 처리로 자연히 폴백됨).
    """
    result = getattr(results, "result", None)
    if result is None and isinstance(results, dict):
        result = results.get("result", results)
    hits = getattr(result, "hits", None)
    if hits is None and isinstance(result, dict):
        hits = result.get("hits")
    return list(hits or [])


def _hit_get(hit, key, default=None):
    """hit(dict 또는 객체)에서 key를 꺼낸다."""
    if isinstance(hit, dict):
        value = hit.get(key, default)
    else:
        value = getattr(hit, key, default)
    return value if value is not None else default


def _hit_score(hit):
    """
    hit의 유사도 점수를 꺼낸다. Pinecone REST 응답(와이어 포맷)은 필드명이 "_score"지만,
    설치된 pinecone SDK(9.x)의 Hit 객체는 이를 "score" 프로퍼티로만 노출하고 "_score"라는
    속성은 없다 (내부 필드명은 score_, rename={"score_": "_score"}는 직렬화용일 뿐). dict
    형태(예: 테스트용 mock)로 들어오는 경우까지 대비해 "score"/"_score" 둘 다 시도한다.
    """
    if isinstance(hit, dict):
        return hit.get("score", hit.get("_score"))
    value = getattr(hit, "score", None)
    if value is None:
        value = getattr(hit, "_score", None)
    return value


def _hit_field(hit, key, default=None):
    """hit.fields에서 key를 꺼낸다. 값이 없거나 빈 문자열이면 default."""
    fields = _hit_get(hit, "fields", {})
    value = fields.get(key) if isinstance(fields, dict) else getattr(fields, key, None)
    return value if value not in (None, "") else default


def _search_category(query_text, subject):
    """
    Pinecone 유사 문제 검색으로 (대분류, 중분류)를 채운다.
    호출 실패/결과 없음/유사도 미달이면 ("미분류", "미분류")로 폴백하고 경고를 남긴다 -
    이 함수는 절대 예외를 밖으로 던지지 않는다 (해설 자체가 막히면 안 되므로).
    """
    try:
        index = _get_index()
        # query=(legacy 딕셔너리)와 filter=(개별 인자)를 동시에 넘기면 SDK가 TypeError를
        # 던진다 ("received both 'query=' and ['filter']") - 그래서 top_k/inputs/filter를
        # 전부 개별 인자로 넘긴다 (SDK가 권장하는 방식이기도 함).
        results = index.search(
            namespace=_NAMESPACE,
            top_k=_TOP_K,
            inputs={"text": query_text},
            filter={"subject": {"$eq": subject}},
        )
        hits = _extract_hits(results)
        if not hits:
            print(f"경고: Pinecone 검색 결과 없음(subject={subject}) - 미분류 처리")
            return "미분류", "미분류"

        top = hits[0]
        score = _hit_score(top)
        if score is None or score < _SIMILARITY_THRESHOLD:
            score_str = f"{score:.2f}" if isinstance(score, (int, float)) else str(score)
            print(f"경고: 유사도 {score_str}가 임계값 {_SIMILARITY_THRESHOLD} 미만 - 미분류 처리")
            return "미분류", "미분류"

        return (
            _hit_field(top, "category_large", "미분류"),
            _hit_field(top, "category_mid", "미분류"),
        )

    except Exception as e:
        print(f"경고: Pinecone 검색 실패({e!r}) - 미분류 처리")
        return "미분류", "미분류"


def classify_problem(ocr_text, mock_override=None, subject=None):
    """
    ocr_text: 1차 Gemini 호출(extract_problem_info)에서 나온 문제 지문 원문. 가공하지 않고
      그대로 Pinecone 쿼리 텍스트로 쓴다 (인덱싱된 문서의 text 필드가 "문제 텍스트\\n보기 텍스트"
      형태라 원문끼리 비교하는 게 맞다고 확인됨).
    mock_override: 지정하면 Pinecone을 거치지 않고 그대로 반환한다. Pinecone 키 없이
      파이프라인의 다른 단계를 테스트할 때 쓴다.
    subject: 1차 호출(problem_extractor.py)이 이미지를 보고 판단한 과목. Pinecone 검색은
      이 과목으로 필터링만 하고, 과목 자체는 여기서 그대로 채택한다 (모듈 docstring 참고).
      없으면(None 또는 "미분류") Pinecone 호출 자체를 생략한다 - 과목을 모르는 상태로
      검색해봐야 결과를 신뢰할 근거가 없다.

    반환: {"과목": str, "대분류": str, "중분류": str}
    """
    if mock_override is not None:
        return mock_override

    if not subject or subject == "미분류":
        print("경고: 1차 호출이 subject를 반환하지 않음 - Pinecone 검색 생략")
        return dict(_UNCLASSIFIED)

    category_large, category_mid = _search_category(ocr_text or "", subject)
    return {"과목": subject, "대분류": category_large, "중분류": category_mid}
