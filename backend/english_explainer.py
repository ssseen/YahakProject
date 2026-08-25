"""
4단계(영어 분기): 영어 문제 해설. Gemini 2차 호출 — v2 파이프라인의 유일한 LLM 호출.
guksagwa_explainer.py와 구조는 같다. 다른 점은 반환 형태 - HTML을 조립하지 않고
구조화된 JSON만 반환한다(지문/보기 단어를 탭하면 뜻이 뜨는 렌더링은 프론트가 담당).

[토큰화 방식 - 정렬 문제 회피]
Gemini에게 지문/보기를 다시 쓰게 하면, 아주 살짝이라도 다르게 재현될 경우(공백/철자/줄바꿈 차이)
프론트에서 "이 단어가 몇 번째 토큰인지" 매칭이 깨진다. 그래서:
  1) 지문(원문)은 ocr_result가 이미 갖고 있는 passage_text를, 보기는 options를 그대로 쓰고,
     Gemini 2차 호출에는 "지문/보기를 다시 쓰지 말라"고 명시한다.
  2) 원문 토큰화는 백엔드가 정규식으로 직접 한다 (_tokenize) - 단어/구두점/공백을 전부 토큰으로
     쪼개서, 토큰을 순서대로 이어붙이면 원문이 그대로 복원된다 (공백도 토큰이라 유실이 없음).
     지문과 각 보기에 독립적으로 적용한다 (지문에 없고 보기에만 나오는 단어도 팝업이 떠야 하므로).
  3) Gemini에는 "단어 -> 뜻" dict(vocabulary) 하나만 요청해서 지문/보기 양쪽 토큰에 공용으로
     매칭한다 (_attach_meanings). dict에 있는데 지문+보기 어디에도 하나도 안 맞는 키가 있으면
     경고를 print한다 (Gemini가 원문에 없는 철자/형태를 줬다는 뜻 - 프론트 단어 팝업 누락의
     원인 추적용). 지문 호출과 보기 호출을 따로 경고하면, 보기에만 나오는 단어가 지문 쪽에서
     "매칭 안 됨"으로 잡혀 거짓 경고가 쏟아지므로, 매칭된 키를 전체(지문+모든 보기)에서 모은
     뒤 마지막에 한 번만 비교한다.

[v2 변경 - 2026-08-25]
- marked_image: 문제 하나만 잘라낸 crop이 아니라 "전체 페이지 + 대상 문항 빨간 박스"를
  받는다(구 problem_img를 대체 - 이름만 바뀌었고 위치 인자라 pipeline.py 호출부는 그대로
  호환된다). 자르지 않고 표시만 하므로 박스 경계가 부정확해도 문맥이 안 잘려나간다 -
  대신 "박스 밖 문제는 참고하지 마라"를 프롬프트에 명시해야 한다.
- range_header/low_conf_lines/subject_hint/category/transcript/reference는 전부 새 키워드
  인자로 추가했다 (기존 위치 인자 뒤에 붙였으므로 구버전 파이프라인의 위치 인자 호출과 호환됨).
- explanation 대신 explanation_text 하나로 화면 해설과 음성 해설을 통합한다. 이 함수의 반환
  dict에는 explanation 키가 없다 - run_pipeline()의 최종 API 응답 필드 "explanation"(프론트와의
  계약, 이름 유지)과는 다른 층이므로, 그 매핑은 pipeline.py 쪽에서 explanation_text를 읽어
  "explanation"으로 옮겨 담는 식으로 처리한다 (pipeline.py 주석 참고).
- question_number(자가 검증용), subject_mismatch(과목 불일치 시 조기 반환)를 추가했다.
"""
import re

import cv2

from gemini_config import get_model, parse_json_response

_WORD_RE = re.compile(r"\w+(?:['’]\w+)?")
_TOKEN_RE = re.compile(r"\w+(?:['’]\w+)?|[^\w\s]|\s+")

_BASE_PROMPT_TEMPLATE = """
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
  "explanation_text": "질문 되짚기(있다면) + 문제 풀이를 하나로 자연스럽게 이어 쓴 설명 (아래 [해설 작성 규칙] 참고)",
  "question_number": 실제로 풀이한 문제 번호(정수)
}}

만약 이 문제가 [문제 유형]에 지정된 과목이 명백히 아니라면(예: 실제로는 수학 문제인데 영어로
지정된 경우), 위 형식 대신 아래 형식만 반환하고 풀이를 시도하지 마세요:
{{"subject_mismatch": "이 문제의 올바른 과목명"}}

[vocabulary 선정 기준 - 반드시 지켜주세요]
- 학습자는 영어를 처음부터 다시 배우는 성인(야학 어르신)입니다. "이 정도는 알겠지"라고
  넘기지 말고, who/i/you/he/she/it/they, be동사(is/am/are/was/were), 관사(a/an/the),
  전치사(in/on/at/for/...) 같은 기초 단어도 전부 포함하세요 - 어려운 단어만 고르지 마세요.
- 지문과 보기에 나오는 의미 있는 단어는 (숫자·구두점 제외) 사실상 전부 포함한다고
  생각하세요. 포함할지 애매하면 무조건 포함하세요 (놓치는 것보다 더 넣는 게 낫습니다).
- 보기(options)에 짧은 단어 하나만 있는 경우(예: Who, What, in, or)도 반드시
  vocabulary에 넣어서 뜻이 붙게 하세요.
- vocabulary의 키(key)는 원문에 실제로 등장한 형태(활용형/복수형 등) 그대로 써야 합니다.
  절대 원형으로 바꾸거나 철자를 고치지 마세요. 원형이 다른 경우 뜻 안에 병기하세요.
  예: "studied": "공부하다 (study의 과거형)"

[해설 작성 규칙 - explanation_text]
- 화면에 보여줄 해설과 음성으로 읽어줄 해설을 따로 만들지 않습니다. explanation_text 하나가
  화면·음성 양쪽의 유일한 원천입니다.
- "질문에 대한 답변:", "문제 해설:" 같은 소제목을 넣지 마세요. TTS가 그대로 읽으므로 한
  덩어리의 자연스러운 말로 이어져야 합니다.
- 음성 질문(아래 [음성 질문] 섹션)이 있을 때만 해설 맨 앞에서 무엇을 물었는지 자연스럽게
  짚고 시작하세요(인식된 문장을 그대로 인용하지 말고 풀어서 말하세요). 음성 질문이 없으면
  곧바로 문제 해설만 쓰세요.
- 음성 질문이 "설명해줘", "풀어줘" 같은 일반적인 요청이면 되짚지 말고 바로 해설하세요
  (되짚으면 "설명해달라고 하셨죠, 설명하면"처럼 순환이 됩니다).
- 음성 질문 인식 결과를 이해할 수 없거나 이 문제와 무관해 보이면, 절대로 질문을 되짚거나
  지어내지 말고 문제 해설만 쓰세요. 이게 가장 중요한 규칙입니다 - 깨진 인식 결과로 억지로
  되짚으면 없는 질문을 지어내는 것이 됩니다.

{optional_sections}
[지문 (OCR로 이미 추출됨 - 참고만 하고 다시 쓰지 마세요)]
{passage}

[보기 (OCR로 이미 추출됨 - 참고만 하고 다시 쓰지 마세요)]
{options_block}

[문제 유형]
과목: {subject}
"""

_MARKED_IMAGE_HINT = (
    "첨부한 이미지는 문제지 페이지 전체이며, 지금 풀어야 할 문제는 빨간 박스로 표시돼 있습니다. "
    "빨간 박스 안의 문제만 푸세요. 박스 밖에 보이는 다른 문제는 절대 참고하지 마세요. "
    "박스 안에 삽화(그림/표/그래프 등)가 있으면 그 내용도 참고해서 문제를 푸세요. "
    "답변은 위에서 지시한 JSON 형식으로만 하고, 이미지를 그리거나 다시 첨부하지 마세요."
)


def _build_optional_sections(range_header, low_conf_lines, subject_hint, category,
                              transcript, reference):
    """
    선택 입력들을 프롬프트 블록으로 조립한다. 값이 없는 섹션은 통째로 생략한다
    (빈 섹션 헤더만 남는 것 방지).
    """
    parts = []

    if range_header:
        parts.append(f"[공통 지시문 - 여러 문제가 이 지시문을 공유합니다]\n{range_header}\n")

    if low_conf_lines:
        joined = " / ".join(low_conf_lines)
        parts.append(
            "[OCR 인식 신뢰도가 낮은 부분]\n"
            f"다음 텍스트는 글자 인식이 불확실할 수 있습니다 - 이미지를 직접 보고 확인하세요: {joined}\n"
        )

    if subject_hint or category:
        hint_lines = []
        if subject_hint:
            hint_lines.append(f"세부 과목 힌트: {subject_hint}")
        if category:
            hint_lines.append(f"유형 힌트: {category}")
        parts.append("[분류 힌트 - 참고용, 이미지가 우선]\n" + "\n".join(hint_lines) + "\n")

    if transcript:
        parts.append(f"[음성 질문 - 학생이 음성으로 물어본 내용]\n\"{transcript}\"\n")

    if reference:
        ref_answer = reference.get("answer", "") if isinstance(reference, dict) else ""
        ref_explanation = reference.get("explanation", "") if isinstance(reference, dict) else ""
        parts.append(
            "[참고 - 유사한 다른 문제의 해설]\n"
            f"정답: {ref_answer}\n해설: {ref_explanation}\n"
            "이건 유사한 다른 문제의 해설입니다. 참고만 하고, 이 문제의 답으로 그대로 가져다 쓰지 "
            "마세요. 지금 풀어야 할 문제와 내용이 다르면 완전히 무시하세요.\n"
        )

    return "\n".join(parts)


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


def explain_english(ocr_result, classification, marked_image=None, user_question="이 문제 좀 알려줘",
                     *, range_header=None, low_conf_lines=None, subject_hint=None,
                     category=None, transcript=None, reference=None):
    """
    ocr_result: extract_problem_info()(v1) 또는 question_locator 결과를 옮겨 담은 동등한 dict.
      passage_text가 지문(보기 제외) 원문, options가 [{"no", "text"}, ...] 보기 목록이다.
      passage_text가 비어 있으면 ocr_text로 폴백한다.
    classification: classify_problem()의 반환값 ({"과목", "대분류", "중분류"}).
    marked_image: 전체 페이지 + 대상 문항을 빨간 박스로 표시한 이미지 (BGR np.ndarray).
      v1 파이프라인은 이 자리에 문제만 잘라낸 crop을 그대로 넘긴다 - 위치 인자라 이름이
      바뀌어도 호출부는 안 깨진다. None이면 텍스트만으로 호출한다.
    range_header: 이 문제가 속한 공통 지시문(예: "[3~4] 다음 중...") 본문. 없으면 None.
    low_conf_lines: 이 문제 범위 안에서 OCR 신뢰도가 낮았던 줄들의 원문 텍스트 리스트
      (인덱스가 아니라 텍스트 - 호출부가 question_locator/clova_client의 인덱스를 이 문제
      범위로 걸러서 텍스트로 넘겨줘야 함). 없으면 None.
    subject_hint, category: Pinecone 다수결/검색 결과로 얻은 세부 과목·유형 힌트. 없으면 None.
    transcript: 학생이 음성으로 한 질문 텍스트. 없으면 None.
    reference: 유사 기출 1건 {"answer":..., "explanation":...} 형태. 없으면 None.

    반환: {"passage": {"text": str, "tokens": [{"text","meaning"}, ...]},
           "options": [{"no": int, "text": str, "tokens": [...]}, ...],
           "translation": {"passage": str, "options": [{"no": int, "text": str}, ...]},
           "explanation_text": str,
           "answer": str, "question_number": int|None, "subject_mismatch": str|None}
    subject_mismatch가 str이면 나머지 필드(translation/vocabulary 등)는 채우지 않고 그 값만
    의미 있다 - 호출부가 이 경우 다른 과목 분기로 재호출해야 한다.
    answer는 원문 문자열 그대로 반환한다 - {number, text} 정규화는 pipeline.py가
    answer_utils.normalize_answer로 한 번만 한다 (국사과와 공용 로직이라 여기서 하지 않음).
    """
    passage = ocr_result.get("passage_text") or ocr_result.get("ocr_text", "") or ""
    options_in = ocr_result.get("options") or []

    options_block = "\n".join(
        f"{opt.get('no')}. {opt.get('text', '')}" for opt in options_in
    ) or "(보기 없음)"

    optional_sections = _build_optional_sections(
        range_header, low_conf_lines, subject_hint, category, transcript, reference
    )

    prompt = _BASE_PROMPT_TEMPLATE.format(
        passage=passage,
        options_block=options_block,
        subject=classification.get("과목", ""),
        optional_sections=optional_sections,
    )
    if user_question:
        prompt += f'\n[질문]\n"{user_question}"\n'

    parts = [prompt]
    if marked_image is not None:
        ok, buf = cv2.imencode(".jpg", marked_image)
        if ok:
            parts = [{"mime_type": "image/jpeg", "data": buf.tobytes()}, _MARKED_IMAGE_HINT, prompt]

    model = get_model(json_mode=True)
    response = model.generate_content(parts)
    parsed = parse_json_response(response.text)

    if parsed.get("subject_mismatch"):
        return {"subject_mismatch": parsed["subject_mismatch"]}

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

    explanation_text = parsed.get("explanation_text", "")

    return {
        "passage": {"text": passage, "tokens": passage_tokens},
        "options": options_out,
        "translation": {
            "passage": parsed.get("translation", ""),
            "options": translation_options_out,
        },
        "explanation_text": explanation_text,
        "answer": parsed.get("answer", ""),
        "question_number": parsed.get("question_number"),
        "subject_mismatch": None,
    }
