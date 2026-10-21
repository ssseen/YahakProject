"""
문제 유형(대분류/중분류) 분류 - Pinecone top-1 + 같은 학력(exam_type) 방식.

[왜 top-1 + 같은 학력인가]
340문제 별도 테스트셋 평가에서 다수결 k=10(대 74.4 / 중 59.7)보다
top-1 + 같은 학력(대 82.4 / 중 68.8)이 가장 정확했다. 유사도 임계값은 효과가 미미해
(76.8 -> 78.0) 채택하지 않았다 - 여기서도 threshold를 두지 않는다.

[동작]
1) user_level(초졸/중졸/고졸)이 유효하면 filter = {subject, exam_type} 로 검색해 top-1을 쓴다.
   -> same_level=True
2) user_level이 없거나, 같은 학력 문제가 하나도 없으면 filter = {subject} 로 다시 검색해
   top-1을 쓴다. -> same_level=False
3) 그래도 없으면 category_large/category_mid = "" (pipeline.py가 빈 값이면 type_info를 만들지 않음)

pipeline.py 호출 규약:
    tr = classify_type(index, query_text, subject, user_level)
    tr.category_large, tr.category_mid, tr.same_level

CLI 스모크 테스트:
    python type_classifier.py "문제 텍스트" 사회 중졸
"""
import os
import sys
from dataclasses import dataclass
from typing import Optional

_NAMESPACE = "questions"
_INDEX_NAME = "geondi-questions"
_LEVEL_FIELD = "exam_type"
VALID_LEVELS = ("초졸", "중졸", "고졸")


@dataclass
class TypeResult:
    category_large: str = ""
    category_mid: str = ""
    same_level: bool = False
    # 디버깅/스모크 테스트용 (pipeline.py는 안 씀)
    source_id: Optional[str] = None      # hit의 original_id (예: 초졸_2026_1회_사회_14)
    source_level: Optional[str] = None   # hit의 exam_type
    score: Optional[float] = None


def _normalize_level(user_level):
    if isinstance(user_level, str) and user_level.strip() in VALID_LEVELS:
        return user_level.strip()
    return None


def _extract_hits(results):
    """SDK 버전에 따라 results.result.hits / dict 접근이 달라 방어적으로 꺼낸다."""
    result = getattr(results, "result", None)
    if result is None and isinstance(results, dict):
        result = results.get("result", results)
    hits = getattr(result, "hits", None)
    if hits is None and isinstance(result, dict):
        hits = result.get("hits")
    return list(hits or [])


def _hit_fields(hit):
    fields = hit.get("fields") if isinstance(hit, dict) else getattr(hit, "fields", None)
    return fields if fields else {}


def _field(fields, key):
    value = fields.get(key) if isinstance(fields, dict) else getattr(fields, key, None)
    return value if value is not None else ""


def _hit_score(hit):
    if isinstance(hit, dict):
        return hit.get("score", hit.get("_score"))
    value = getattr(hit, "score", None)
    return value if value is not None else getattr(hit, "_score", None)


def _search_top1(index, query_text, flt):
    """filter 조건으로 검색해 top-1 hit만 돌려준다 (없으면 None)."""
    # query=(legacy dict)와 filter=를 같이 넘기면 SDK가 TypeError를 던지므로
    # top_k/inputs/filter를 전부 개별 인자로 넘긴다 (classifier.py와 동일).
    results = index.search(
        namespace=_NAMESPACE,
        top_k=1,
        inputs={"text": query_text},
        filter=flt,
    )
    hits = _extract_hits(results)
    return hits[0] if hits else None


def _to_result(hit, same_level):
    fields = _hit_fields(hit)
    return TypeResult(
        category_large=_field(fields, "category_large"),
        category_mid=_field(fields, "category_mid"),
        same_level=same_level,
        source_id=_field(fields, "original_id") or None,
        source_level=_field(fields, _LEVEL_FIELD) or None,
        score=_hit_score(hit),
    )


def classify_type(index, query_text, subject, user_level=None):
    """
    index: Pinecone Index 클라이언트 (pipeline.py의 _get_pinecone_index())
    query_text: question_locator가 만든 문제 텍스트
    subject: 과목 (사회/과학/국어/영어/수학) - metadata 'subject' 필터로 쓴다
    user_level: 사용자가 고른 학력(초졸/중졸/고졸). 없거나 값이 이상하면 학력 필터 없이 진행.

    검색 실패(네트워크 등)는 예외를 그대로 올린다 - pipeline.py가 잡아서 경고만 찍고
    기존 category로 폴백한다.
    """
    if not query_text or not subject:
        return TypeResult()

    subject_filter = {"subject": {"$eq": subject}}

    level = _normalize_level(user_level)
    if level:
        hit = _search_top1(
            index, query_text,
            {"$and": [subject_filter, {_LEVEL_FIELD: {"$eq": level}}]},
        )
        if hit is not None:
            return _to_result(hit, same_level=True)
        print(f"경고: 같은 학력({level}, {subject}) 문제가 없어 전체 학력에서 검색")

    hit = _search_top1(index, query_text, subject_filter)
    if hit is None:
        print(f"경고: Pinecone 검색 결과 없음(subject={subject}) - 유형 미분류")
        return TypeResult()
    return _to_result(hit, same_level=False)


def _get_index():
    from dotenv import load_dotenv
    from pinecone import Pinecone

    load_dotenv()
    api_key = os.getenv("PINECONE_API_KEY")
    if not api_key:
        raise RuntimeError("PINECONE_API_KEY가 .env에 없음 (backend/ 폴더에서 실행했는지 확인)")
    return Pinecone(api_key=api_key).Index(_INDEX_NAME)


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        print('사용법: python type_classifier.py "문제 텍스트" <과목> [초졸|중졸|고졸]')
        sys.exit(1)

    text, subj = sys.argv[1], sys.argv[2]
    lvl = sys.argv[3] if len(sys.argv) == 4 else None
    r = classify_type(_get_index(), text, subj, lvl)
    print(f"category_large = {r.category_large!r}")
    print(f"category_mid   = {r.category_mid!r}")
    print(f"same_level     = {r.same_level}")
    print(f"(근거 hit: {r.source_id} / 학력={r.source_level} / score={r.score})")