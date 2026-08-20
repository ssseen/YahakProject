"""
국어/사회/과학(국사과)/영어 해설 파이프라인 - 엔드투엔드 오케스트레이션.

  1) crop_pointed_question으로 손끝 주변 crop (vision_processor.py, 기존 코드)
  2) extract_problem_info로 Gemini 1차 호출 (OCR / 키워드 / 삽화유무)
  3) classify_problem으로 유형 분류 (지금은 Pinecone 연동 전, 목업)
  4) 국어/사회/과학이면 explain_guksagwa로, 영어면 explain_english로 Gemini 2차 호출,
     나머지(수학)는 미지원으로 반환
  5) 최종 JSON 조립 (콘솔 출력 / 파일 저장은 호출부 몫)

수학 분기는 아직 없다 - GUKSAGWA_SUBJECTS/ENGLISH_SUBJECTS 어디에도 없는 과목은 전부
"미지원"으로 빠지고, 나중에 수학 분기를 추가할 자리만 남겨뒀다 (run_pipeline의
if/elif/else 부분).
"""
import base64
import json
import time

import cv2
import numpy as np

from vision_processor import compute_crop_bounds
from problem_extractor import extract_problem_info
from classifier import classify_problem
from guksagwa_explainer import explain_guksagwa
from english_explainer import explain_english
from answer_utils import normalize_answer

GUKSAGWA_SUBJECTS = {"국어", "사회", "과학"}
ENGLISH_SUBJECTS = {"영어"}

_ILLUSTRATION_THUMB_SIZE = (330, 150)  # (width, height)


def _make_illustration_data_uri(illustration_img):
    """
    illustration_img(BGR np.ndarray, _crop_illustration이 잘라낸 삽화)를 330x150 고정
    크기 PNG로 만들어 data URI로 반환한다.

    원본 비율은 항상 유지한다 - 가로/세로 중 더 많이 줄여야(또는 늘려야) 하는 쪽 비율에
    맞춰 리사이즈하므로(letterbox), 도형/그래프가 눌리거나 늘어나는 왜곡이 없다. 330x150
    보다 작은 삽화는 확대도 한다 (안 그러면 흰 여백 속에 너무 작게 박혀서 안 보임 - 비율은
    어차피 유지되므로 확대해도 찌그러짐 문제는 없음). 남는 여백은 흰색으로 채운다.

    실패하면(이미지가 비었거나 인코딩 실패) None을 반환한다.
    """
    target_w, target_h = _ILLUSTRATION_THUMB_SIZE
    h, w = illustration_img.shape[:2]
    if h == 0 or w == 0:
        return None

    scale = min(target_w / w, target_h / h)
    new_w = max(1, round(w * scale))
    new_h = max(1, round(h * scale))
    interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
    resized = cv2.resize(illustration_img, (new_w, new_h), interpolation=interpolation)

    canvas = np.full((target_h, target_w, 3), 255, dtype=np.uint8)
    x_off = (target_w - new_w) // 2
    y_off = (target_h - new_h) // 2
    canvas[y_off:y_off + new_h, x_off:x_off + new_w] = resized

    ok, buf = cv2.imencode(".png", canvas)
    if not ok:
        return None
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode("ascii")


def _crop_illustration(cropped_img, bbox):
    """
    extract_problem_info가 돌려준 illustration_bbox(cropped_img 기준 백분율)를
    픽셀 좌표로 바꿔서 삽화 부분만 잘라낸다. bbox가 없거나 값이 이상하면 None을 반환한다.

    지금은 이 결과를 2차 호출 첨부에는 쓰지 않는다 (has_illustration=true일 때 2차 호출에는
    삽화 crop 대신 cropped 전체를 붙인다 - run_pipeline 참고, 이유는 그쪽 주석 참고).
    좌표 추출/보관 자체는 나중에 수학 분기의 Pillow 오버레이 기준점으로 쓸 예정이라 유지한다.
    """
    if not bbox:
        print("경고: has_illustration=true인데 illustration_bbox가 없음")
        return None
    h, w = cropped_img.shape[:2]
    try:
        x1 = int(w * bbox["x1_percent"] / 100)
        y1 = int(h * bbox["y1_percent"] / 100)
        x2 = int(w * bbox["x2_percent"] / 100)
        y2 = int(h * bbox["y2_percent"] / 100)
    except (KeyError, TypeError):
        print(f"경고: illustration_bbox 파싱 실패 (bbox={bbox})")
        return None

    x1, x2 = sorted((max(0, min(w, x1)), max(0, min(w, x2))))
    y1, y2 = sorted((max(0, min(h, y1)), max(0, min(h, y2))))
    if x2 - x1 < 10 or y2 - y1 < 10:
        print(f"경고: illustration_bbox가 너무 작아 유효하지 않음 (bbox={bbox} -> "
              f"x1={x1},y1={y1},x2={x2},y2={y2})")
        return None

    return cropped_img[y1:y2, x1:x2].copy()


def run_pipeline(image_path, x, y, stt_text=None, user_question="이 문제 좀 알려줘",
                  classification_override=None, save_path=None):
    """
    image_path: 문제지 사진 파일 경로.
    x, y: find_finger_tip 등으로 이미 추출된 손끝 픽셀 좌표 (원본 이미지 기준). 손끝을 못
      찾았으면 둘 다 None으로 넘긴다 - 이 경우 compute_crop_bounds를 아예 호출하지 않고
      원본 이미지 전체를 그대로 쓴다. 가짜 좌표(예: 이미지 중앙)를 만들어서 넘기면
      compute_crop_bounds가 그 근처를 "문제 하나"로 잘라내버려서, 문제지에 여러 문제가
      있을 때 엉뚱한 문제를 해설하게 되므로 절대 하지 말 것.
    stt_text: 학생이 음성으로 한 질문 (없으면 None).
    classification_override: 3단계(분류) 결과를 강제로 지정. Pinecone 연동 전에
      국사과 분기를 테스트하고 싶을 때 사용 (classifier.classify_problem 참고).
    save_path: 지정하면 최종 결과를 JSON 파일로도 저장한다.

    반환 (해설 응답 명세서 - 국사과/영어 분기 참고):
      국사과 성공 시 {"status": "success", "type": "guksagwa", "subject": str,
                    "problem_type": str, "problem_text": str, "explanation": str,
                    "answer": {"number": int|None, "text": str}, ...}
      영어 성공 시   {"status": "success", "type": "english", "subject": str,
                    "problem_type": str, "passage": {...}, "options": [...],
                    "translation": {...}, "explanation": str,
                    "answer": {"number": int|None, "text": str}, ...}
      미지원 과목    {"status": "unsupported_subject", "subject": str, "message": str}
      재촬영 요청    {"status": "retake", "message": str}
        - 1차 호출이 ocr_text를 못 뽑았을 때(빈 문자열) 여기서 멈춘다. 손끝이 없어서 문제를
          특정 못 했거나, 손끝은 있는데 사진이 흐려 OCR 자체가 실패한 경우 등 - finger_detected
          여부와 무관하게 ocr_text가 비면 항상 이 경로로 빠진다. 빈 지문으로 2차 호출(해설
          생성)까지 가봐야 의미가 없으므로 classify_problem도 호출하지 않고 여기서 반환한다.
      오류 시        {"status": "error", "message": str}

    성공/미지원 응답에는 공통으로 finger_detected(bool), has_illustration(bool),
    illustration_bbox(dict|None), illustration(삽화를 330x150 흰 배경 letterbox PNG로 만든
    data URI 문자열|None)이 붙는다.
    """
    pipeline_start = time.perf_counter()

    img = cv2.imread(image_path)
    if img is None:
        return {"status": "error", "message": f"이미지를 읽을 수 없음: {image_path}"}

    finger_detected = x is not None and y is not None

    if finger_detected:
        t_crop = time.perf_counter()
        bounds = compute_crop_bounds(img, x, y)
        if bounds is None:
            # 폴백: 손끝 주변 crop을 못 찾으면 원본 이미지 전체를 그대로 쓴다.
            h, w = img.shape[:2]
            x_start, y_start, x_end, y_end = 0, 0, w, h
            cropped = img
        else:
            x_start, y_start, x_end, y_end = bounds
            cropped = img[y_start:y_end, x_start:x_end].copy()
        print(f"0. crop (compute_crop_bounds) 완료 ({time.perf_counter() - t_crop:.2f}초)")

        crop_w, crop_h = x_end - x_start, y_end - y_start
        x_percent = (x - x_start) / crop_w * 100 if crop_w else 0.0
        y_percent = (y - y_start) / crop_h * 100 if crop_h else 0.0
    else:
        print("경고: 손끝 좌표 없음 - crop 생략, 원본 이미지 전체를 사용")
        cropped = img
        x_percent, y_percent = None, None

    print("1. Gemini 1차 호출 (OCR/키워드 추출)...")
    t_ocr = time.perf_counter()
    ocr_result = extract_problem_info(cropped, x_percent, y_percent, stt_text)
    print("   ->", ocr_result)
    print(f"   ({time.perf_counter() - t_ocr:.2f}초)")

    if not (ocr_result.get("ocr_text") or "").strip():
        print("경고: 1차 호출이 ocr_text를 비워서 반환함 - retake 요청")
        print(f"전체 소요 시간: {time.perf_counter() - pipeline_start:.2f}초")
        return {
            "status": "retake",
            "message": "어떤 문제를 물어보는지 알 수 없어요. 손가락으로 문제를 짚고 다시 찍어주세요.",
        }

    print("2. 유형 분류 (Pinecone 검색)...")
    t_classify = time.perf_counter()
    classification = classify_problem(
        ocr_result.get("ocr_text", ""),
        classification_override,
        subject=ocr_result.get("subject"),
    )
    print("   ->", classification)
    print(f"   ({time.perf_counter() - t_classify:.2f}초)")

    has_illustration = bool(ocr_result.get("has_illustration"))

    # 좌표는 여기서 미리 검증/보관해둔다 (나중에 수학 분기 Pillow 오버레이용 좌표 정확도
    # 데이터를 국사과 경로에서부터 쌓아두려는 목적). _crop_illustration이 성공(=좌표가
    # 파싱 가능하고 크기가 유효함)한 경우에만 백분율 좌표 그대로 남기고, 실패하면 null.
    illustration_bbox_out = None
    illustration_data_uri = None
    if has_illustration:
        t_illustration = time.perf_counter()
        illustration_crop = _crop_illustration(cropped, ocr_result.get("illustration_bbox"))
        if illustration_crop is not None:
            illustration_bbox_out = ocr_result.get("illustration_bbox")
            illustration_data_uri = _make_illustration_data_uri(illustration_crop)
        print(f"   삽화 crop 완료 ({time.perf_counter() - t_illustration:.2f}초)")

    subject = classification.get("과목")
    problem_type = f"{classification.get('대분류', '')} > {classification.get('중분류', '')}"

    # 1차 호출이 과목을 못 준 경우(subject가 None이거나 "미분류") - OCR 자체는 멀쩡한데
    # 과목 판단만 실패한 것이므로 해설을 아예 안 주는 대신 국사과 분기로 폴백한다
    # (국사과 해설이 텍스트 기반이라 가장 범용적).
    subject_unknown = subject is None or subject == "미분류"
    if subject_unknown:
        print(f"경고: 1차 호출이 과목을 판단하지 못함(subject={subject!r}) -> 국사과 해설로 폴백")

    if subject in GUKSAGWA_SUBJECTS or subject_unknown:
        # 2차 호출에는 삽화만 잘라낸 crop 대신 cropped(문제 전체)를 붙인다 - Gemini가 준
        # 삽화 좌표가 부정확하면 축 레이블이나 "그림 (가)" 같은 캡션이 crop에서 잘려나가는데,
        # 이게 에러 없이 해설만 조용히 틀리는 형태로 나타나서 추적이 어렵기 때문.
        attach_img = cropped if has_illustration else None
        illustration_attached = has_illustration

        print("3. Gemini 2차 호출 (국사과 해설)...")
        t_explain = time.perf_counter()
        explanation = explain_guksagwa(ocr_result, classification, attach_img, user_question)
        print(f"   ({time.perf_counter() - t_explain:.2f}초)")
        result = {
            "status": "success",
            "type": "guksagwa",
            "subject": subject,
            "problem_type": problem_type,
            "problem_text": ocr_result.get("ocr_text", ""),
            "explanation": explanation.get("explanation", ""),
            "answer": normalize_answer(explanation.get("answer")),
            "illustration_attached": illustration_attached,
        }
    elif subject in ENGLISH_SUBJECTS:
        # 국사과와 동일한 규칙: 삽화가 있으면 삽화 crop이 아니라 cropped(문제 전체)를 붙인다.
        attach_img = cropped if has_illustration else None
        illustration_attached = has_illustration

        print("3. Gemini 2차 호출 (영어 해설)...")
        t_explain = time.perf_counter()
        explanation = explain_english(ocr_result, classification, attach_img, user_question)
        print(f"   ({time.perf_counter() - t_explain:.2f}초)")
        options_out = explanation.get("options", [])
        result = {
            "status": "success",
            "type": "english",
            "subject": subject,
            "problem_type": problem_type,
            "passage": explanation.get("passage", {"text": "", "tokens": []}),
            "options": options_out,
            "translation": explanation.get("translation", {"passage": "", "options": []}),
            "explanation": explanation.get("explanation", ""),
            # options을 같이 넘겨서, Gemini가 번호만 주고 본문을 비운 경우 보기에서 채워 넣는다.
            "answer": normalize_answer(explanation.get("answer"), options_out),
            "illustration_attached": illustration_attached,
        }
    else:
        result = {
            "status": "unsupported_subject",
            "subject": subject,
            "message": f"{subject} 분기는 아직 구현되지 않았습니다 (국어/사회/과학/영어만 지원)",
        }

    result["finger_detected"] = finger_detected
    result["has_illustration"] = has_illustration
    result["illustration_bbox"] = illustration_bbox_out
    result["illustration"] = illustration_data_uri

    print(f"전체 소요 시간: {time.perf_counter() - pipeline_start:.2f}초")

    if save_path:
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

    return result


if __name__ == "__main__":
    import sys

    if len(sys.argv) not in (2, 4):
        print("사용법: python pipeline.py <이미지경로>            (손끝 좌표 자동 인식)")
        print("       python pipeline.py <이미지경로> <x> <y>    (좌표 직접 지정)")
        sys.exit(1)

    image_path = sys.argv[1]

    if len(sys.argv) == 4:
        x, y = int(sys.argv[2]), int(sys.argv[3])
    else:
        import cv2
        from vision_processor import find_finger_tip

        img = cv2.imread(image_path)
        if img is None:
            print(f"이미지를 읽을 수 없음: {image_path}")
            sys.exit(1)
        tip, tip_msg = find_finger_tip(img)
        if tip is None:
            print(f"손끝을 못 찾음: {tip_msg} (좌표를 직접 지정해주세요)")
            sys.exit(1)
        x, y = tip["x"], tip["y"]
        print(f"손끝 좌표 자동 인식: ({x}, {y})")

    final_result = run_pipeline(image_path, x, y)
    print(json.dumps(final_result, ensure_ascii=False, indent=2))
