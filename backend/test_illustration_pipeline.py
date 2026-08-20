"""
삽화(illustration) 기능 + 전체 파이프라인을 직접 눈으로 확인하기 위한 수동 테스트 스크립트.

실행 예시 (backend 폴더에서, venv로):
    .\\venv\\Scripts\\python.exe test_illustration_pipeline.py
    .\\venv\\Scripts\\python.exe test_illustration_pipeline.py ..\\영어.png
    .\\venv\\Scripts\\python.exe test_illustration_pipeline.py ..\\영어.png 240 100   (좌표 직접 지정)

인자 없이 실행하면 프로젝트 루트의 영어.png를 사용한다.

결과물 (backend/illustration_test_output/):
  - result.json      : run_pipeline()의 전체 응답 (답변/해설 포함)
  - illustration.png : illustration 필드를 디코딩한 실제 이미지 (330x150, 삽화 없으면 생성 안 됨)

한글/비-ASCII 파일명은 cv2.imread가 못 읽는 Windows/OpenCV 특성 때문에, 내부적으로
파일을 임시 ASCII 경로로 복사한 뒤 그 경로로 run_pipeline을 호출한다 (pipeline.py 자체는
건드리지 않음 - 이 스크립트 안에서만 우회).
"""
import base64
import os
import shutil
import sys
import tempfile

import cv2

from pipeline import run_pipeline
from vision_processor import find_finger_tip

OUT_DIR = os.path.join(os.path.dirname(__file__), "illustration_test_output")


def _safe_ascii_copy(image_path):
    ext = os.path.splitext(image_path)[1] or ".png"
    fd, tmp_path = tempfile.mkstemp(suffix=ext)
    os.close(fd)
    shutil.copyfile(image_path, tmp_path)
    return tmp_path


def main():
    default_image = os.path.join(os.path.dirname(__file__), "..", "영어.png")
    image_path = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else default_image)

    if not os.path.exists(image_path):
        print(f"이미지를 찾을 수 없음: {image_path}")
        sys.exit(1)

    safe_path = _safe_ascii_copy(image_path)
    try:
        if len(sys.argv) > 3:
            x, y = int(sys.argv[2]), int(sys.argv[3])
            print(f"좌표 직접 지정: ({x}, {y})")
        else:
            img = cv2.imread(safe_path)
            tip, msg = find_finger_tip(img)
            if tip is not None:
                x, y = tip["x"], tip["y"]
                print(f"손끝 좌표 자동 인식: ({x}, {y})")
            else:
                h, w = img.shape[:2]
                x, y = w // 2, h // 2
                print(f"손가락 못 찾음({msg}) -> 이미지 중앙 좌표 사용: ({x}, {y})")

        os.makedirs(OUT_DIR, exist_ok=True)
        result = run_pipeline(safe_path, x, y, save_path=os.path.join(OUT_DIR, "result.json"))

        print("\n" + "=" * 60)
        print("status:", result.get("status"))
        print("type:", result.get("type"))
        print("subject:", result.get("subject"))
        print("problem_type:", result.get("problem_type"))
        print("answer:", result.get("answer"))
        print("explanation:\n", result.get("explanation"))
        print("has_illustration:", result.get("has_illustration"))

        illustration_uri = result.get("illustration")
        if illustration_uri:
            png_bytes = base64.b64decode(illustration_uri.split(",", 1)[1])
            illustration_path = os.path.join(OUT_DIR, "illustration.png")
            with open(illustration_path, "wb") as f:
                f.write(png_bytes)
            print(f"\nillustration 저장됨: {illustration_path}")
        else:
            print("\nillustration 없음 (has_illustration=False 이거나 crop 실패)")

        print(f"\n전체 결과 JSON: {os.path.join(OUT_DIR, 'result.json')}")
        print("=" * 60)
    finally:
        os.remove(safe_path)


if __name__ == "__main__":
    main()
