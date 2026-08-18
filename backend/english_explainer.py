"""
4단계(영어 분기): 영어 문제 해설. Gemini 2차 호출.
guksagwa_explainer.py와 구조는 같다 (1차 호출 결과 + 분류 결과를 받아 Gemini 2차 호출로
해설을 만든다). 다른 점은 반환 형태 - HTML을 조립하지 않고 구조화된 JSON만 반환한다
(지문/보기 단어를 탭하면 뜻이 뜨는 것 같은 렌더링은 프론트엔드가 담당).

[토큰화 방식 - 정렬 문제 회피]
Gemini에게 지문/보기를 다시 쓰게 하면, 아주 살짝이라도 다르게 재현될 경우(공백/철자/줄바꿈 차이)
프론트에서 "이 단어가 몇 번째 토큰인지" 매칭이 깨진다. 그래서:
  1) 지문(원문)은 1차 호출(extract_problem_info)이 이미 뽑아둔 passage_text를, 보기는 options를
     그대로 쓰고, Gemini 2차 호출에는 "지문/보기를 다시 쓰지 말라"고 명시한다.
  2) 원문 토큰화는 백엔드가 정규식으로 직접 한다 (_tokenize) - 단어/구두점/공백을 전부 토큰으로
     쪼개서, 토큰을 순서대로 이어붙이면 원문이 그대로 복원된다 (공백도 토큰이라 유실이 없음).
     지문과 각 보기에 독립적으로 적용한다 (지문에 없고 보기에만 나오는 단어도 팝업이 떠야 하므로).
  3) Gemini에는 "단어 -> 뜻" dict(vocabulary) 하나만 요청해서 지문/보기 양쪽 토큰에 공용으로
     매칭한다 (_attach_meanings). dict에 있는데 지문+보기 어디에도 하나도 안 맞는 키가 있으면
     경고를 print한다 (Gemini가 원문에 없는 철자/형태를 줬다는 뜻 - 프론트 단어 팝업 누락의
     원인 추적용). 지문 호출과 보기 호출을 따로 경고하면, 보기에만 나오는 단어가 지문 쪽에서
     "매칭 안 됨"으로 잡혀 거짓 경고가 쏟아지므로, 매칭된 키를 전체(지문+모든 보기)에서 모은
     뒤 마지막에 한 번만 비교한다.

has_illustration 처리는 guksagwa_explainer.py와 동일: 문제에 삽화가 있으면(그림 묘사 문제 등)
2차 호출에 삽화만 잘라낸 crop이 아니라 문제 전체를 crop한 이미지(problem_img)를 첨부한다
(이유는 guksagwa_explainer.py 모듈 docstring 참고 - 삽화 bbox가 부정확하면 캡션/보기가
잘려나갈 수 있어서).
"""
import re

import cv2

from gemini_config import get_model, parse_json_response

_WORD_RE = re.compile(r"\w+(?:['’]\w+)?")
_TOKEN_RE = re.compile(r"\w+(?:['’]\w+)?|[^\w\s]|\s+")

_PROMPT_TEMPLATE = """
당신은 야학 어르신을 위한 영어 선생님입니다.

[규칙]
- 쉬운 우리말 사용
- 친근한 말투
- 아래 JSON 형식으로만 답하세요. 다른 설명, 인사말, 마크다운 코드블록 없이 순수 JSON만 출력하세요.
- 지문(passage)과 보기(options)는 절대 다시 쓰지 마세요. 아래 JSON에 원문을 그대로 포함하지
  마세요 (백엔드가 따로 처리합니다). 참고만 하세요.

{{
  "translation": "지문 전체를 쉬운 우리말로 자연스럽게 번역",
  "option_translations": {{"1": "보기 1번을 쉬운 우리말로 번역", "2": "...", "3": "...", "4": "..."}},
  "vocabulary": {{"지문 또는 보기에 나온 그대로의 단어(활용형 포함)": "뜻 (원형이 다르면 뜻 뒤에 원형을 병기)"}},
  "answer": "정답 번호와 내용",
  "explanation": "문제를 어떻게 풀어야 하는지 쉬운 우리말로 자연스럽게 한 문단 설명 (단계 나열 아님)"
}}

[vocabulary 선정 기준 - 반드시 지켜주세요]
- 관사(a/an/the), 전치사(in/on/at/for/...), be동사(is/am/are/was/were), 기초 대명사
  (I/you/he/she/it/they/...) 등 너무 기본적인 단어는 제외하세요.
- 검정고시 영어 수준 응시자가 모를 만한 단어 위주로 골라주세요. 지문뿐 아니라 보기에만
  나오는 어려운 단어도 포함하세요.
- 포함할지 애매한 단어는 포함하세요 (놓치는 것보다 더 넣는 게 낫습니다).
- vocabulary의 키(key)는 원문에 실제로 등장한 형태(활용형/복수형 등) 그대로 써야 합니다.
  절대 원형으로 바꾸거나 철자를 고치지 마세요. 원형이 다른 경우 뜻 안에 병기하세요.
  예: "studied": "공부하다 (study의 과거형)"

[지문 (OCR로 이미 추출됨 - 참고만 하고 다시 쓰지 마세요)]
{passage}

[보기 (OCR로 이미 추출됨 - 참고만 하고 다시 쓰지 마세요)]
{options_block}

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


def _tokenize(text):
    """
    정규식으로 텍스트(지문 또는 보기 하나)를 토큰화한다. 단어/구두점/공백을 전부 토큰으로
    남기기 때문에 토큰을 순서대로 이어붙이면 원문이 그대로 복원된다 (프론트에서 원문 재구성 가능).
    """
    return _TOKEN_RE.findall(text or "")


def _match_tokens(tokens, vocab_lower, matched_keys):
    """
    vocab_lower(소문자로 변환된 vocabulary dict)를 토큰에 매칭해서
    [{"text", "meaning"}, ...] 를 만든다. 비교는 소문자 변환 기준 (문장 맨 앞 대문자화 등
    대소문자 차이만 있는 경우 허용).

    매칭에 성공한 키는 matched_keys(호출부가 지문/보기 전체에 걸쳐 공유하는 set)에 기록만
    하고, 여기서는 경고를 찍지 않는다 - 지문과 보기를 각각 이 함수로 따로 호출하기 때문에,
    여기서 바로 경고하면 "보기에만 나오는 단어"가 지문 쪽 호출에서 매번 매칭 실패로 잡혀
    거짓 경고가 쏟아진다. 실제 미매칭 여부는 호출부가 모든 호출이 끝난 뒤
    _warn_unmatched_vocabulary로 한 번만 판단한다.
    """
    result = []
    for tok in tokens:
        meaning = None
        if _WORD_RE.fullmatch(tok):
            key = tok.lower()
            if key in vocab_lower:
                meaning = vocab_lower[key]
                matched_keys.add(key)
        result.append({"text": tok, "meaning": meaning})
    return result


def _warn_unmatched_vocabulary(vocab_lower, matched_keys):
    """
    vocab_lower에는 있는데 지문+보기 어디에도 하나도 안 맞은 키가 있으면 경고를 남긴다 -
    Gemini가 원문에 없는 철자/원형을 줬다는 뜻이라, 이 경고가 없으면 프론트에서 왜 특정
    단어에 팝업이 안 뜨는지 추적하기 어렵다.
    """
    for key in vocab_lower:
        if key not in matched_keys:
            print(f"경고: vocabulary 단어 '{key}'가 지문/보기 토큰과 매칭되지 않음 (팝업 누락 가능, 원인 추적용)")


def explain_english(ocr_result, classification, problem_img=None, user_question="이 문제 좀 알려줘"):
    """
    ocr_result: extract_problem_info()의 반환값
      ({"ocr_text", "passage_text", "options", "keywords", "has_illustration", ...}).
      passage_text가 지문(보기 제외) 원문, options가 [{"no", "text"}, ...] 보기 목록이다.
      passage_text가 비어 있으면 ocr_text로 폴백한다 (1차 호출이 옛 스키마를 줬거나 실패한 경우).
    classification: classify_problem()의 반환값 ({"과목", "대분류", "중분류"}).
    problem_img: 문제에 삽화가 있을 때, 문제 전체를 crop한 이미지 (BGR np.ndarray, pipeline.py의
      cropped를 그대로 넘겨받음 - guksagwa_explainer.explain_guksagwa와 동일한 규칙).
      없으면 None - 이 경우 텍스트만으로 호출한다.

    반환: {"passage": {"text": str, "tokens": [{"text","meaning"}, ...]},
           "options": [{"no": int, "text": str, "tokens": [...]}, ...],
           "translation": {"passage": str, "options": [{"no": int, "text": str}, ...]},
           "explanation": str, "answer": str}
    answer는 원문 문자열 그대로 반환한다 - {number, text} 정규화는 pipeline.py가
    answer_utils.normalize_answer로 한 번만 한다 (국사과와 공용 로직이라 여기서 하지 않음).
    """
    passage = ocr_result.get("passage_text") or ocr_result.get("ocr_text", "") or ""
    options_in = ocr_result.get("options") or []

    options_block = "\n".join(
        f"{opt.get('no')}. {opt.get('text', '')}" for opt in options_in
    ) or "(보기 없음)"

    prompt = _PROMPT_TEMPLATE.format(
        passage=passage,
        options_block=options_block,
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

    vocab_lower = {k.lower(): v for k, v in (parsed.get("vocabulary") or {}).items()}
    matched_keys = set()

    passage_tokens = _match_tokens(_tokenize(passage), vocab_lower, matched_keys)

    option_translations = parsed.get("option_translations") or {}
    options_out = []
    translation_options_out = []
    for opt in options_in:
        no = opt.get("no")
        text = opt.get("text", "") or ""
        options_out.append({
            "no": no,
            "text": text,
            "tokens": _match_tokens(_tokenize(text), vocab_lower, matched_keys),
        })
        translation_options_out.append({
            "no": no,
            "text": option_translations.get(str(no)) or option_translations.get(no) or "",
        })

    _warn_unmatched_vocabulary(vocab_lower, matched_keys)

    return {
        "passage": {"text": passage, "tokens": passage_tokens},
        "options": options_out,
        "translation": {
            "passage": parsed.get("translation", ""),
            "options": translation_options_out,
        },
        "explanation": parsed.get("explanation", ""),
        "answer": parsed.get("answer", ""),
    }
