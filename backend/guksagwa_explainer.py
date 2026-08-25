"""
4단계: 국어/사회/과학(국사과) 문제 해설. Gemini 2차 호출 — v2 파이프라인의 유일한 LLM 호출.
출력은 해석/풀이/정답 텍스트만 (그래프, 이미지 오버레이, 단어 팝업 없음).

[v2 변경 - 2026-08-25]
- marked_image: 문제 하나만 잘라낸 crop이 아니라 "전체 페이지 + 대상 문항 빨간 박스"를
  받는다(구 problem_img를 대체 - 이름만 바뀌었고 위치 인자라 pipeline.py 호출부는 그대로
  호환된다). 자르지 않고 표시만 하므로 삽화 좌표(bbox)가 부정확해도 축 레이블이나
  "그림 (가)" 같은 캡션이 잘려나가지 않는다 - 대신 "박스 밖 문제는 참고하지 마라"를
  프롬프트에 명시해야 한다.
- range_header/low_conf_lines/subject_hint/category/transcript/reference는 전부 새 키워드
  인자로 추가했다 (기존 위치 인자 뒤에 붙였으므로 구버전 파이프라인의 위치 인자 호출과 호환됨).
- explanation 대신 explanation_text 하나로 화면 해설과 음성 해설을 통합한다. 이 함수의 반환
  dict에는 explanation 키가 없다 - run_pipeline()의 최종 API 응답 필드 "explanation"(프론트와의
  계약, 이름 유지)과는 다른 층이므로, 그 매핑은 pipeline.py 쪽에서 explanation_text를 읽어
  "explanation"으로 옮겨 담는 식으로 처리한다 (pipeline.py 주석 참고).
- question_number(자가 검증용), subject_mismatch(과목 불일치 시 조기 반환)를 추가했다.
"""
import cv2

from gemini_config import get_model, parse_json_response

_BASE_PROMPT_TEMPLATE = """
당신은 야학 어르신을 위한 선생님입니다.

[규칙]
- 쉬운 우리말 사용
- 친근한 말투
- 아래 JSON 형식으로만 답하세요. 다른 설명, 인사말, 마크다운 코드블록 없이 순수 JSON만 출력하세요.

{{"explanation_text": "질문 되짚기(있다면) + 문제 풀이를 하나로 자연스럽게 이어 쓴 설명 (아래 [해설 작성 규칙] 참고)",
  "answer": "정답 번호와 내용",
  "question_number": 실제로 풀이한 문제 번호(정수)}}

만약 이 문제가 [문제 유형]에 지정된 과목이 명백히 아니라면(예: 실제로는 수학 문제인데 국사과로
지정된 경우), 위 형식 대신 아래 형식만 반환하고 풀이를 시도하지 마세요:
{{"subject_mismatch": "이 문제의 올바른 과목명"}}

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
[문제 내용 (OCR)]
{ocr_text}

[핵심 키워드]
{keywords}

[문제 유형]
과목: {subject} / 대분류: {major} / 중분류: {minor}
"""

_MARKED_IMAGE_HINT = (
    "첨부한 이미지는 문제지 페이지 전체이며, 지금 풀어야 할 문제는 빨간 박스로 표시돼 있습니다. "
    "빨간 박스 안의 문제만 푸세요. 박스 밖에 보이는 다른 문제는 절대 참고하지 마세요. "
    "박스 안에 삽화(그림/표/그래프 등)가 있으면 그 내용(수치, 그림 속 관계 등)도 참고해서 "
    "문제를 푸세요. 답변은 위에서 지시한 JSON 텍스트 형식으로만 하고, 이미지를 그리거나 다시 "
    "첨부하지 마세요."
)


def _build_optional_sections(range_header, low_conf_lines, subject_hint, category,
                              transcript, reference):
    """
    선택 입력들을 프롬프트 블록으로 조립한다. 값이 없는 섹션은 통째로 생략한다
    (빈 섹션 헤더만 남는 것 방지). english_explainer.py의 동명 함수와 로직은 같다 -
    프롬프트 본문 구조가 서로 달라 공용 모듈로 뽑기보다 각자 두었다.
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


def _apply_korean_key_fallback(parsed):
    """
    프롬프트로 영문 키를 요청해도, Gemini가 가끔 지시를 어기고 예전 한글 키
    ({"해설","정답"}) 나 구버전 영문 키({"explanation"})로 돌려줄 수 있다. 이걸 그냥
    parsed.get("explanation_text", "")로 읽으면 에러 없이 빈 해설이 그대로 프론트로
    나가버린다 - 조용히 틀리는 형태라 원인 추적이 제일 어려운 실패 모드다. 그래서 반환
    직전에 대체 키가 있으면 explanation_text로 옮기고 경고를 남긴다.
    """
    if "explanation_text" not in parsed:
        if "해설" in parsed:
            print("경고: Gemini가 국사과 해설을 한글 키('해설')로 반환함 - explanation_text로 폴백 매핑")
            parsed["explanation_text"] = parsed.get("해설", "")
        elif "explanation" in parsed:
            print("경고: Gemini가 국사과 해설을 구버전 키('explanation')로 반환함 - explanation_text로 폴백 매핑")
            parsed["explanation_text"] = parsed.get("explanation", "")
    if "answer" not in parsed and "정답" in parsed:
        print("경고: Gemini가 국사과 정답을 한글 키('정답')로 반환함 - answer로 폴백 매핑")
        parsed["answer"] = parsed.get("정답", "")
    return parsed


def explain_guksagwa(ocr_result, classification, marked_image=None, user_question="이 문제 좀 알려줘",
                      *, range_header=None, low_conf_lines=None, subject_hint=None,
                      category=None, transcript=None, reference=None):
    """
    ocr_result: extract_problem_info()(v1) 또는 question_locator 결과를 옮겨 담은 동등한 dict
      ({"ocr_text", "keywords", ...}).
    classification: classify_problem()의 반환값 ({"과목", "대분류", "중분류"}).
    marked_image: 전체 페이지 + 대상 문항을 빨간 박스로 표시한 이미지 (BGR np.ndarray).
      v1 파이프라인은 이 자리에 문제만 잘라낸 crop을 그대로 넘긴다 - 위치 인자라 이름이
      바뀌어도 호출부는 안 깨진다. None이면 텍스트만으로 호출한다.
    range_header: 이 문제가 속한 공통 지시문 본문. 없으면 None.
    low_conf_lines: 이 문제 범위 안에서 OCR 신뢰도가 낮았던 줄들의 원문 텍스트 리스트. 없으면 None.
    subject_hint, category: Pinecone 다수결/검색 결과로 얻은 세부 과목·유형 힌트. 없으면 None.
    transcript: 학생이 음성으로 한 질문 텍스트. 없으면 None.
    reference: 유사 기출 1건 {"answer":..., "explanation":...} 형태. 없으면 None.

    반환: {"explanation_text": str,
           "answer": str, "question_number": int|None, "subject_mismatch": str|None}
    subject_mismatch가 str이면 나머지 필드는 빈 값이다 - 호출부가 이 경우 다른 과목 분기로
    재호출해야 한다.
    answer는 원문 문자열 그대로 반환한다 - {number, text} 정규화는 pipeline.py가
    answer_utils.normalize_answer로 한 번만 한다 (english_explainer.py와 공용 로직이라
    여기서 하지 않음).
    """
    optional_sections = _build_optional_sections(
        range_header, low_conf_lines, subject_hint, category, transcript, reference
    )

    prompt = _BASE_PROMPT_TEMPLATE.format(
        ocr_text=ocr_result.get("ocr_text", ""),
        keywords=", ".join(ocr_result.get("keywords", [])),
        subject=classification.get("과목", ""),
        major=classification.get("대분류", ""),
        minor=classification.get("중분류", ""),
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

    parsed = _apply_korean_key_fallback(parsed)
    explanation_text = parsed.get("explanation_text", "")

    return {
        "explanation_text": explanation_text,
        "answer": parsed.get("answer", ""),
        "question_number": parsed.get("question_number"),
        "subject_mismatch": None,
    }
