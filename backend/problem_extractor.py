"""
2단계: 크롭된 이미지를 Gemini에 보내서 OCR 텍스트 / 키워드 / 삽화 유무를 뽑아낸다.
"""
import cv2

from gemini_config import get_model, parse_json_response

_FORMAT_INSTRUCTION = """
반드시 아래 JSON 형식으로만 답하세요. 다른 설명, 인사말, 마크다운 코드블록 없이 순수 JSON만 출력하세요.
{
  "subject": "국어" 또는 "영어" 또는 "수학" 또는 "사회" 또는 "과학" 중 반드시 하나만 고르세요.
    다른 값(예: "미분류", "기타")은 절대 쓰지 마세요. 이미지를 직접 보고 판단하세요 -
    글자 모양(한글/영어/숫자·수식), 문제 유형(계산식, 지문 해석, 도표 등)을 근거로 삼으세요.
  "ocr_text": "학생이 가리킨 문제의 지문과 보기를 포함한 전체 텍스트",
  "passage_text": "보기(①②③④ 등 선택지)를 제외한 지문·발문 원문. 선택지가 없는 문제면
    ocr_text와 동일하게 채우세요.",
  "options": [{"no": 1, "text": "보기 1번 내용"}, {"no": 2, "text": "보기 2번 내용"}, ...] 형식으로,
    선택지(①②③④ 등)가 있으면 번호별로 분리하세요. 선택지가 없는 문제면 빈 배열 []로 두세요.
  "keywords": ["문제 내용을 대표하는 핵심 키워드", "..."],
  "has_illustration": true 또는 false. 판정 기준:
    - true: 문제 해결에 필요한 도형/그래프/표/지도/실험도/사료 등이 있는 경우
    - false: 텍스트만으로 문제가 성립하는 경우 (장식용 삽화 포함)
    - 애매하면 true로 판정하세요 (놓치는 비용이 불필요하게 포함시키는 비용보다 큽니다)
  "illustration_bbox": has_illustration가 true일 때만, 그 삽화가 이미지 안에서 차지하는
    대략적인 사각형 범위. 아래 형식으로, 백분율(0~100)로 답하세요:
    {"x1_percent": 왼쪽 경계, "y1_percent": 위쪽 경계, "x2_percent": 오른쪽 경계, "y2_percent": 아래쪽 경계}
    has_illustration가 false면 이 필드는 null로 하세요.
}

[매우 중요 - passage_text와 options 작성 규칙]
- 이미지에 보이는 원문 그대로 옮겨 적으세요. 철자, 띄어쓰기, 문장부호, 대소문자를 단 한 글자도
  고치거나 요약하거나 다듬지 마세요. 절대 다시 쓰거나(재구성) 의역하지 마세요.
- 이 두 필드는 나중에 원문과 글자 단위로 대조하는 데 쓰입니다. 조금이라도 다르게 옮기면
  뒤 단계가 깨집니다.
"""


def extract_problem_info(cropped_img, x_percent, y_percent, stt_text=None):
    """
    cropped_img: crop_pointed_question(또는 폴백으로 원본)이 잘라낸 문제 영역 이미지 (BGR np.ndarray).
    x_percent, y_percent: crop된 이미지 안에서 손끝이 왼쪽/위쪽으로부터 몇 % 지점인지
      (vision_processor.compute_crop_bounds가 계산한 crop 범위 기준). 손끝을 못 찾아서
      crop 자체를 건너뛴 경우(pipeline.py 참고) 둘 다 None이 넘어온다 - 이 경우 가짜 좌표
      (예: 50%/50%)를 만들어서 넘기지 않는다. 손가락이 이미지 정중앙에 있다는 거짓 정보를
      주면 Gemini가 오답을 오히려 확신 있게 낼 위험이 있기 때문. 대신 "손끝 정보 없음"을
      솔직히 알리고, 판단이 안 서면 ocr_text를 비워도 된다고 명시적으로 허용한다
      (아무 문제나 억지로 고르게 하면 틀려도 티가 안 남 - pipeline.py가 이 빈 값을 보고
      retake를 요청한다).
    stt_text: 학생이 음성으로 질문한 내용이 있으면 그 텍스트 (없으면 None).

    프롬프트에는 이미지 -> 좌표 설명(자연어) -> (stt_text 있으면 추가) -> 출력 형식 지시 순서로 넣는다.
    crop 자체가 정밀한 경계가 아니므로, 좌표는 참고용 힌트로만 주고 실제 판단은 이미지 안에
    보이는 손가락을 보고 Gemini가 직접 하도록 안내한다.

    illustration_bbox는 나중에 파이프라인에서 삽화 부분만 따로 crop해서 2차 호출에 넘길 때
    쓰인다 (문제 전체를 다시 보내는 대신 삽화만).

    반환: {"subject": str, "ocr_text": str, "passage_text": str,
           "options": [{"no": int, "text": str}, ...], "keywords": [str, ...],
           "has_illustration": bool,
           "illustration_bbox": {"x1_percent","y1_percent","x2_percent","y2_percent"} 또는 None}

    subject는 classify_problem(classifier.py)에 그대로 전달되어 과목 분기를 결정한다 -
    Pinecone은 유사 문제 검색기일 뿐이라 그쪽 결과의 subject는 신뢰할 수 없으므로(비슷하게
    생긴 "다른 문제"의 과목일 뿐), 이미지를 직접 보는 이 1차 호출이 과목 판단을 전담한다.

    passage_text/options는 영어 분기(english_explainer.py)에서 지문/보기를 분리해 토큰화하는 데
    쓰인다. 국사과 분기는 ocr_text만 쓰므로 이 두 필드를 무시해도 무방하다(하위 호환).
    """
    ok, buf = cv2.imencode(".jpg", cropped_img)
    if not ok:
        raise ValueError("이미지 인코딩 실패")
    image_part = {"mime_type": "image/jpeg", "data": buf.tobytes()}

    if x_percent is not None and y_percent is not None:
        coordinate_hint = (
            "첨부한 이미지는 학생이 손가락으로 짚은 문제 주변을 넉넉하게 잘라낸 사진입니다. "
            "정확한 경계는 아니니, 이미지 안에 보이는 손가락이 실제로 어떤 문제를 가리키는지 "
            "직접 보고 판단하세요. 참고로 손가락 끝은 이 이미지에서 왼쪽 기준 약 "
            f"{x_percent:.0f}%, 위쪽 기준 약 {y_percent:.0f}% 지점 근처에 있습니다."
        )
    else:
        coordinate_hint = (
            "첨부한 이미지는 학생이 손가락으로 짚지 않은 문제지 사진입니다 (손끝 위치 정보 없음). "
            "이미지 안에 문제가 여러 개 있을 수 있습니다. 질문 내용과 가장 관련 있어 보이는 문제를 "
            "고르세요. 어떤 문제를 묻는지 판단하기 어려우면, 억지로 고르지 말고 ocr_text를 "
            "빈 문자열로 두세요."
        )

    parts = [image_part, coordinate_hint]
    if stt_text:
        parts.append(f'학생이 음성으로 한 질문: "{stt_text}"')
    parts.append(_FORMAT_INSTRUCTION)

    model = get_model(json_mode=True)
    response = model.generate_content(parts)
    return parse_json_response(response.text)
