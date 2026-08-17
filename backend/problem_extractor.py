"""
2단계: 크롭된 이미지를 Gemini에 보내서 OCR 텍스트 / 키워드 / 삽화 유무를 뽑아낸다.
"""
import cv2

from gemini_config import get_model, parse_json_response

_FORMAT_INSTRUCTION = """
반드시 아래 JSON 형식으로만 답하세요. 다른 설명, 인사말, 마크다운 코드블록 없이 순수 JSON만 출력하세요.
{
  "ocr_text": "학생이 가리킨 문제의 지문과 보기를 포함한 전체 텍스트",
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
"""


def extract_problem_info(cropped_img, x_percent, y_percent, stt_text=None):
    """
    cropped_img: crop_pointed_question(또는 폴백으로 원본)이 잘라낸 문제 영역 이미지 (BGR np.ndarray).
    x_percent, y_percent: crop된 이미지 안에서 손끝이 왼쪽/위쪽으로부터 몇 % 지점인지
      (vision_processor.compute_crop_bounds가 계산한 crop 범위 기준).
    stt_text: 학생이 음성으로 질문한 내용이 있으면 그 텍스트 (없으면 None).

    프롬프트에는 이미지 -> 좌표 설명(자연어) -> (stt_text 있으면 추가) -> 출력 형식 지시 순서로 넣는다.
    crop 자체가 정밀한 경계가 아니므로, 좌표는 참고용 힌트로만 주고 실제 판단은 이미지 안에
    보이는 손가락을 보고 Gemini가 직접 하도록 안내한다.

    illustration_bbox는 나중에 파이프라인에서 삽화 부분만 따로 crop해서 2차 호출에 넘길 때
    쓰인다 (문제 전체를 다시 보내는 대신 삽화만).

    반환: {"ocr_text": str, "keywords": [str, ...], "has_illustration": bool,
           "illustration_bbox": {"x1_percent","y1_percent","x2_percent","y2_percent"} 또는 None}
    """
    ok, buf = cv2.imencode(".jpg", cropped_img)
    if not ok:
        raise ValueError("이미지 인코딩 실패")
    image_part = {"mime_type": "image/jpeg", "data": buf.tobytes()}

    coordinate_hint = (
        "첨부한 이미지는 학생이 손가락으로 짚은 문제 주변을 넉넉하게 잘라낸 사진입니다. "
        "정확한 경계는 아니니, 이미지 안에 보이는 손가락이 실제로 어떤 문제를 가리키는지 "
        "직접 보고 판단하세요. 참고로 손가락 끝은 이 이미지에서 왼쪽 기준 약 "
        f"{x_percent:.0f}%, 위쪽 기준 약 {y_percent:.0f}% 지점 근처에 있습니다."
    )

    parts = [image_part, coordinate_hint]
    if stt_text:
        parts.append(f'학생이 음성으로 한 질문: "{stt_text}"')
    parts.append(_FORMAT_INSTRUCTION)

    model = get_model(json_mode=True)
    response = model.generate_content(parts)
    return parse_json_response(response.text)
