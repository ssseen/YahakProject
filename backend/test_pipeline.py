"""
파이프라인 엔드투엔드 테스트 스크립트.

샘플 이미지 1장 + 손끝 좌표로 crop -> Gemini 1차 호출 -> 유형 분류 -> Gemini 2차 호출
(국사과)까지 전체가 실제로 도는지 확인한다. 실제 Gemini API를 호출하므로
backend/.env에 GEMINI_API_KEY가 설정되어 있어야 한다.
"""
import json
import os

import cv2

from vision_processor import find_finger_tip
from pipeline import run_pipeline

SAMPLE_IMAGE = os.path.join(os.path.dirname(__file__), "..", "image", "16.jpg")
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "test_pipeline_output.json")


def main():
    img = cv2.imread(SAMPLE_IMAGE)
    if img is None:
        print("샘플 이미지를 못 찾음:", SAMPLE_IMAGE)
        return

    tip, msg = find_finger_tip(img)
    if tip is None:
        print("손끝을 못 찾음:", msg)
        return
    x, y = tip["x"], tip["y"]
    print(f"손끝 좌표: ({x}, {y})")

    # SAMPLE_IMAGE(16.jpg)는 수학 시험지라 classify_problem을 그대로 두면
    # "수학"으로 분류되어 국사과 분기를 안 탄다 (수학/영어는 아직 미구현이라 정상 동작).
    # 지금은 국사과 파이프라인 자체가 끝까지 도는지 확인하는 게 목적이므로,
    # classification_override로 사회 문제인 척 강제 지정해서 전체 경로를 검증한다.
    override = {"과목": "사회", "대분류": "정치", "중분류": "헌법"}

    result = run_pipeline(
        SAMPLE_IMAGE, x, y,
        classification_override=override,
        save_path=OUTPUT_PATH,
    )

    print("\n=== 최종 결과 ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\nhas_illustration: {result.get('has_illustration')}")
    print(f"2차 호출 이미지 첨부 여부(illustration_attached): {result.get('illustration_attached')}")
    print(f"\n(결과는 {OUTPUT_PATH} 에도 저장됨)")


if __name__ == "__main__":
    main()
