"""
Gemini 1차(problem_extractor.py) vs EasyOCR(ocr_extractor.py) 속도/결과 비교용 실험 스크립트.

실행 예시 (backend 폴더에서, venv로):
    .\\venv\\Scripts\\python.exe test_ocr_vs_gemini.py ..\\사회1.png
    .\\venv\\Scripts\\python.exe test_ocr_vs_gemini.py ..\\사회1.png 240 100   (좌표 직접 지정)

인자 없이 실행하면 프로젝트 루트의 영어.png를 사용한다.

한글/비-ASCII 파일명은 cv2.imread가 못 읽는 Windows/OpenCV 특성 때문에, test_illustration_
pipeline.py와 동일하게 내부적으로 임시 ASCII 경로로 복사한 뒤 그 경로를 쓴다.

주의: EasyOCR 쪽 첫 실행은 Reader 생성(모델 로딩)이 몇 초~몇십 초 걸릴 수 있어서, 이
스크립트는 로딩 시간과 순수 추론 시간(ocr_ms)을 분리해서 보여준다 - 공정한 비교는
"로딩 후 순수 추론 시간" 기준으로 볼 것.
"""
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # backend/ 루트 (vision_processor 등)

import cv2

from vision_processor import compute_crop_bounds, find_finger_tip
from problem_extractor import extract_problem_info
from ocr_extractor import extract_problem_info_ocr, _get_reader
from classifier import classify_problem


def _safe_ascii_copy(image_path):
    ext = os.path.splitext(image_path)[1] or ".png"
    fd, tmp_path = tempfile.mkstemp(suffix=ext)
    os.close(fd)
    shutil.copyfile(image_path, tmp_path)
    return tmp_path


def _crop(img, x, y):
    bounds = compute_crop_bounds(img, x, y)
    if bounds is None:
        return img
    x1, y1, x2, y2 = bounds
    return img[y1:y2, x1:x2].copy()


def main():
    default_image = os.path.join(os.path.dirname(__file__), "..", "영어.png")
    image_path = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else default_image)

    if not os.path.exists(image_path):
        print(f"이미지를 찾을 수 없음: {image_path}")
        sys.exit(1)

    safe_path = _safe_ascii_copy(image_path)
    try:
        img = cv2.imread(safe_path)
        if img is None:
            print(f"이미지를 읽을 수 없음: {image_path}")
            sys.exit(1)

        if len(sys.argv) > 3:
            x, y = int(sys.argv[2]), int(sys.argv[3])
            print(f"좌표 직접 지정: ({x}, {y})")
        else:
            tip, msg = find_finger_tip(img)
            if tip is not None:
                x, y = tip["x"], tip["y"]
                print(f"손끝 좌표 자동 인식: ({x}, {y})")
            else:
                h, w = img.shape[:2]
                x, y = w // 2, h // 2
                print(f"손가락 못 찾음({msg}) -> 이미지 중앙 좌표 사용: ({x}, {y})")

        cropped = _crop(img, x, y)
        h, w = img.shape[:2]
        x_percent = x / w * 100
        y_percent = y / h * 100

        print("\n" + "=" * 60)
        print("[EasyOCR Reader 로딩 중 - 최초 1회만 느림]")
        t_load = time.perf_counter()
        _get_reader()
        print(f"Reader 로딩 시간: {time.perf_counter() - t_load:.2f}초 (비교 대상 아님)")

        print("\n" + "=" * 60)
        print("1) Gemini 1차 (problem_extractor.extract_problem_info)")
        t0 = time.perf_counter()
        gemini_result = extract_problem_info(cropped, x_percent, y_percent)
        gemini_sec = time.perf_counter() - t0
        print(f"   소요 시간: {gemini_sec:.2f}초")
        print(f"   subject: {gemini_result.get('subject')}")
        print(f"   has_illustration: {gemini_result.get('has_illustration')}")
        print(f"   ocr_text: {gemini_result.get('ocr_text')}")
        print(f"   options: {gemini_result.get('options')}")

        print("\n" + "=" * 60)
        print("2) EasyOCR (ocr_extractor.extract_problem_info_ocr)")
        t0 = time.perf_counter()
        ocr_result = extract_problem_info_ocr(cropped)
        ocr_sec = time.perf_counter() - t0
        print(f"   소요 시간: {ocr_sec:.2f}초 (순수 추론: {ocr_result['ocr_ms'] / 1000:.2f}초)")
        print(f"   subject: {ocr_result.get('subject')} (OCR로는 판단 불가 - 항상 None)")
        print(f"   has_illustration: {ocr_result.get('has_illustration')} (OCR로는 판단 불가 - 항상 False)")
        print(f"   ocr_text: {ocr_result.get('ocr_text')}")
        print(f"   options: {ocr_result.get('options')}")

        # Pinecone 분류 비교. OCR은 subject를 판단 못 하므로(ocr_extractor.py 참고), 이
        # 비교에서는 Gemini가 판단한 subject를 양쪽에 똑같이 빌려 써서 "OCR 텍스트 품질이
        # Pinecone 매칭에 얼마나 영향을 주는지"만 따로 떼어 본다 - subject 자체를 못 정하는
        # 문제는 이미 알고 있는 별개의 한계라 여기서 다시 확인할 필요는 없음.
        subject_for_pinecone = gemini_result.get("subject")

        print("\n" + "=" * 60)
        print(f"3) Pinecone 분류 비교 (subject='{subject_for_pinecone}'로 양쪽 동일하게 고정)")

        t0 = time.perf_counter()
        gemini_classification = classify_problem(
            gemini_result.get("ocr_text", ""), subject=subject_for_pinecone
        )
        gemini_pinecone_sec = time.perf_counter() - t0
        print(f"   [Gemini 텍스트 기준] {gemini_classification}  ({gemini_pinecone_sec:.2f}초)")

        t0 = time.perf_counter()
        ocr_classification = classify_problem(
            ocr_result.get("ocr_text", ""), subject=subject_for_pinecone
        )
        ocr_pinecone_sec = time.perf_counter() - t0
        print(f"   [EasyOCR 텍스트 기준] {ocr_classification}  ({ocr_pinecone_sec:.2f}초)")

        print("\n" + "=" * 60)
        print("[요약]")
        print(f"1차 추출 - Gemini: {gemini_sec:.2f}초 / EasyOCR: {ocr_sec:.2f}초  (약 {gemini_sec / ocr_sec:.1f}배 {'빠름' if ocr_sec < gemini_sec else '느림'})")
        print(f"Pinecone 분류 - Gemini 텍스트: {gemini_classification.get('대분류')} > {gemini_classification.get('중분류')}")
        print(f"Pinecone 분류 - OCR 텍스트:    {ocr_classification.get('대분류')} > {ocr_classification.get('중분류')}")
        print("=" * 60)
    finally:
        os.remove(safe_path)


if __name__ == "__main__":
    main()
