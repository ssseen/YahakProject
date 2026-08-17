"""
4단계(영어 분기): 영어 문제 해설. Gemini 2차 호출.
guksagwa_explainer.py와 구조는 같다 (1차 호출 결과 + 분류 결과를 받아 Gemini 2차 호출로
해설을 만든다). 다른 점은 반환 형태 - HTML을 조립하지 않고 구조화된 JSON만 반환한다
(지문 단어를 탭하면 뜻이 뜨는 것 같은 렌더링은 프론트엔드가 담당).

[토큰화 방식 - 정렬 문제 회피]
Gemini에게 지문을 다시 쓰게 하면, 아주 살짝이라도 다르게 재현될 경우(공백/철자/줄바꿈 차이)
프론트에서 "이 단어가 지문의 몇 번째 토큰인지" 매칭이 깨진다. 그래서:
  1) 지문(원문)은 1차 호출(extract_problem_info)이 이미 뽑아둔 ocr_text를 그대로 쓰고,
     Gemini 2차 호출에는 "지문을 다시 쓰지 말라"고 명시한다.
  2) 원문 토큰화는 백엔드가 정규식으로 직접 한다 (_tokenize) - 단어/구두점/공백을 전부 토큰으로
     쪼개서, 토큰을 순서대로 이어붙이면 원문이 그대로 복원된다 (공백도 토큰이라 유실이 없음).
  3) Gemini에는 "단어 -> 뜻" dict(vocabulary)만 요청한다. 매칭은 소문자로 바꿔서 토큰과
     비교한다 (_attach_meanings). dict에 있는데 토큰과 하나도 안 맞는 키가 있으면 경고를 print
     한다 (Gemini가 지문에 없는 철자/형태를 줬다는 뜻 - 프론트 단어 팝업 누락의 원인 추적용).

has_illustration 처리는 guksagwa_explainer.py와 동일: 문제에 삽화가 있으면(그림 묘사 문제 등)
2차 호출에 삽화만 잘라낸 crop이 아니라 문제 전체를 crop한 이미지(problem_img)를 첨부한다
(이유는 guksagwa_explainer.py 모듈 docstring 참고 - 삽화 bbox가 부정확하면 캡션/보기가
잘려나갈 수 있어서).
"""
import re

import cv2

from gemini_config import get_model, parse_json_response

_WORD_RE = re.compile(r"\w+(?:'\w+)?")
_TOKEN_RE = re.compile(r"\w+(?:'\w+)?|[^\w\s]|\s+")

_PROMPT_TEMPLATE = """
당신은 야학 어르신을 위한 영어 선생님입니다.

[규칙]
- 쉬운 우리말 사용
- 친근한 말투
- 아래 JSON 형식으로만 답하세요. 다른 설명, 인사말, 마크다운 코드블록 없이 순수 JSON만 출력하세요.
- 지문(passage)은 절대 다시 쓰지 마세요. 아래 JSON에 지문 원문을 포함하지 마세요 (백엔드가 따로 처리합니다).

{{
  "translation": "지문 전체를 쉬운 우리말로 자연스럽게 번역",
  "vocabulary": {{"지문에 나온 그대로의 단어(활용형 포함)": "뜻 (원형이 다르면 뜻 뒤에 원형을 병기)"}},
  "answer": "정답 번호와 내용",
  "explanation_steps": ["문제를 어떻게 풀어야 하는지 단계별로 쉬운 우리말 설명", "..."]
}}

[vocabulary 선정 기준 - 반드시 지켜주세요]
- 관사(a/an/the), 전치사(in/on/at/for/...), be동사(is/am/are/was/were), 기초 대명사
  (I/you/he/she/it/they/...) 등 너무 기본적인 단어는 제외하세요.
- 검정고시 영어 수준 응시자가 모를 만한 단어 위주로 골라주세요.
- 포함할지 애매한 단어는 포함하세요 (놓치는 것보다 더 넣는 게 낫습니다).
- vocabulary의 키(key)는 지문에 실제로 등장한 형태(활용형/복수형 등) 그대로 써야 합니다.
  절대 원형으로 바꾸거나 철자를 고치지 마세요. 원형이 다른 경우 뜻 안에 병기하세요.
  예: "studied": "공부하다 (study의 과거형)"

[지문 (OCR로 이미 추출됨 - 참고만 하고 다시 쓰지 마세요)]
{passage}

[문제 유형]
과목: {subject}

[질문]
"{user_question}"
"""

_ILLUSTRATION_HINT = (
    "첨부한 이미지는 이 문제 전체를 crop한 사진입니다. 이 안에 포함된 삽화(그림/표/그래프 등)의 "
    "내용을 참고해서 문제를 푸세요. "
    "단, 답변은 위에서 지시한 JSON 형식으로만 하고, 이미지를 그리거나 다시 첨부하지 마세요."
)


def _tokenize(passage):
    """
    정규식으로 지문을 토큰화한다. 단어/구두점/공백을 전부 토큰으로 남기기 때문에
    토큰을 순서대로 이어붙이면 원문이 그대로 복원된다 (프론트에서 원문 재구성 가능).
    """
    return _TOKEN_RE.findall(passage or "")


def _attach_meanings(tokens, vocabulary):
    """
    vocabulary(지문에 등장한 형태 그대로의 단어 -> 뜻 dict)를 토큰에 매칭한다.
    비교는 소문자 변환 기준 (문장 맨 앞 대문자화 등 대소문자 차이만 있는 경우 허용).

    vocabulary에는 있는데 토큰과 하나도 안 맞는 키는 조용히 넘어가지 않고 경고를 남긴다 -
    Gemini가 지문에 없는 철자/원형을 줬다는 뜻이라, 이 경고가 없으면 프론트에서 왜 특정
    단어에 팝업이 안 뜨는지 추적하기 어렵다.
    """
    vocab_lower = {k.lower(): v for k, v in vocabulary.items()}
    matched_keys = set()

    result = []
    for tok in tokens:
        meaning = None
        if _WORD_RE.fullmatch(tok):
            key = tok.lower()
            if key in vocab_lower:
                meaning = vocab_lower[key]
                matched_keys.add(key)
        result.append({"text": tok, "meaning": meaning})

    for key in vocab_lower:
        if key not in matched_keys:
            print(f"경고: vocabulary 단어 '{key}'가 지문 토큰과 매칭되지 않음 (팝업 누락 가능, 원인 추적용)")

    return result


def explain_english(ocr_result, classification, problem_img=None, user_question="이 문제 좀 알려줘"):
    """
    ocr_result: extract_problem_info()의 반환값 ({"ocr_text", "keywords", "has_illustration", ...}).
      ocr_text가 곧 영어 지문(passage) 원문이다.
    classification: classify_problem()의 반환값 ({"과목", "대분류", "중분류"}).
    problem_img: 문제에 삽화가 있을 때, 문제 전체를 crop한 이미지 (BGR np.ndarray, pipeline.py의
      cropped를 그대로 넘겨받음 - guksagwa_explainer.explain_guksagwa와 동일한 규칙).
      없으면 None - 이 경우 텍스트만으로 호출한다.

    반환: {"passage": str, "tokens": [{"text": str, "meaning": str|None}, ...],
           "translation": str, "answer": str, "explanation_steps": [str, ...]}
    """
    passage = ocr_result.get("ocr_text", "") or ""

    prompt = _PROMPT_TEMPLATE.format(
        passage=passage,
        subject=classification.get("과목", ""),
        user_question=user_question,
    )

    parts = [prompt]
    if problem_img is not None:
        ok, buf = cv2.imencode(".jpg", problem_img)
        if ok:
            parts = [{"mime_type": "image/jpeg", "data": buf.tobytes()}, _ILLUSTRATION_HINT, prompt]

    model = get_model(json_mode=True)
    response = model.generate_content(parts)
    parsed = parse_json_response(response.text)

    tokens = _tokenize(passage)
    tokens_with_meaning = _attach_meanings(tokens, parsed.get("vocabulary") or {})

    return {
        "passage": passage,
        "tokens": tokens_with_meaning,
        "translation": parsed.get("translation", ""),
        "answer": parsed.get("answer", ""),
        "explanation_steps": parsed.get("explanation_steps", []),
    }
