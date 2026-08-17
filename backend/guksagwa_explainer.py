"""
4단계: 국어/사회/과학(국사과) 문제 해설. Gemini 2차 호출.
출력은 해석/풀이/정답 텍스트만 (그래프, 이미지 오버레이, 단어 팝업 없음).
입력은 1차 호출 결과(OCR 텍스트)와 분류 결과가 기본이고, 문제에 삽화(그림/표/그래프)가
있으면 문제 전체를 crop한 이미지(problem_img)도 같이 보낸다 - 안 그러면 삽화 안에 있는
정보(그래프 수치 등)를 텍스트만으로는 놓칠 수 있다. 삽화 부분만 잘라내지 않고 문제 전체를
보내는 이유: 삽화 좌표(bbox)가 부정확하면 축 레이블이나 "그림 (가)" 같은 캡션이 잘려나갈
수 있는데, 이는 에러 없이 해설만 조용히 틀리는 형태로 나타나 추적이 어렵기 때문
(pipeline.py의 run_pipeline 참고). 출력이 텍스트만이라는 것과 입력에 이미지가 들어가는
건 별개.
"""
import cv2

from gemini_config import get_model, parse_json_response

_PROMPT_TEMPLATE = """
당신은 야학 어르신을 위한 선생님입니다.

[규칙]
- 쉬운 우리말 사용
- 친근한 말투
- 아래 JSON 형식으로만 답하세요. 다른 설명, 인사말, 마크다운 코드블록 없이 순수 JSON만 출력하세요.

{{"해설": "문제를 어떻게 풀어야 하는지 자연스러운 설명", "정답": "정답 번호와 내용"}}

[문제 내용 (OCR)]
{ocr_text}

[핵심 키워드]
{keywords}

[문제 유형]
과목: {subject} / 대분류: {major} / 중분류: {minor}

[질문]
"{user_question}"
"""

_ILLUSTRATION_HINT = (
    "첨부한 이미지는 이 문제 전체를 crop한 사진입니다. 이 안에 포함된 삽화(그림/표/그래프 등)의 "
    "내용(수치, 그림 속 관계 등)을 참고해서 문제를 푸세요. "
    "단, 답변은 위에서 지시한 JSON 텍스트 형식으로만 하고, 이미지를 그리거나 다시 첨부하지 마세요."
)


def explain_guksagwa(ocr_result, classification, problem_img=None, user_question="이 문제 좀 알려줘"):
    """
    ocr_result: extract_problem_info()의 반환값 ({"ocr_text", "keywords", "has_illustration", ...}).
    classification: classify_problem()의 반환값 ({"과목", "대분류", "중분류"}).
    problem_img: 문제에 삽화가 있을 때, 문제 전체를 crop한 이미지 (BGR np.ndarray, pipeline.py의
      cropped를 그대로 넘겨받음 - 삽화만 잘라낸 crop이 아님, 모듈 docstring 참고).
      없으면 None - 이 경우 텍스트만으로 호출한다.

    반환: {"해설": str, "정답": str}
    """
    prompt = _PROMPT_TEMPLATE.format(
        ocr_text=ocr_result.get("ocr_text", ""),
        keywords=", ".join(ocr_result.get("keywords", [])),
        subject=classification.get("과목", ""),
        major=classification.get("대분류", ""),
        minor=classification.get("중분류", ""),
        user_question=user_question,
    )

    parts = [prompt]
    if problem_img is not None:
        ok, buf = cv2.imencode(".jpg", problem_img)
        if ok:
            parts = [{"mime_type": "image/jpeg", "data": buf.tobytes()}, _ILLUSTRATION_HINT, prompt]

    model = get_model(json_mode=True)
    response = model.generate_content(parts)
    return parse_json_response(response.text)
