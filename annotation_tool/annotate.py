"""
정확도 검증용 라벨링 도구

testimage 폴더의 모든 jpg에 대해 순서대로:
  1) 좌클릭 -> 손끝 좌표 (x, y) 기록 (녹색 점 표시)
  2) 콘솔에 문항번호 입력
  3) 마우스 드래그 -> 바운딩박스 지정 (빨간 사각형 표시)
  4) Enter -> 확정하고 다음 이미지로 이동

단축키:
  r    : 현재 단계(손끝 좌표 또는 바운딩박스)를 다시 찍기
  Enter: 확정 후 다음 이미지
  ESC  : 중단 (지금까지 완료한 결과는 JSON에 저장된 상태로 유지)

한 번 완료한 이미지는 결과 파일에 기록되며, 스크립트를 다시 실행하면
이미 완료된 이미지는 건너뛰고 이어서 진행합니다.

창 크기는 이미지 크기와 무관하게 항상 고정(CANVAS_W x CANVAS_H)입니다.
이미지는 그 안에 비율을 유지한 채 맞춰지고 남는 공간은 회색 여백으로 채워집니다.
"""
import json
from pathlib import Path

import cv2
import numpy as np

BASE_DIR = Path(__file__).resolve().parent
IMAGE_DIR = BASE_DIR / "testimage"
OUTPUT_PATH = BASE_DIR / "annotations.json"

CANVAS_W = 1280
CANVAS_H = 820
WINDOW_NAME = "annotate"
WINDOW_POS = (50, 50)
PAD_COLOR = (40, 40, 40)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def imread_unicode(path: Path):
    """cv2.imread는 Windows에서 한글 등 비ASCII 경로를 못 읽으므로 우회."""
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


class ImageState:
    def __init__(self):
        self.mode = "point"        # "point" -> "bbox" 순서로 진행
        self.point = None          # (x, y) 원본 이미지 좌표
        self.bbox = None           # (x_min, y_min, x_max, y_max) 원본 이미지 좌표
        self.drag_start = None     # 드래그 시작점 (캔버스 좌표)
        self.dragging = False
        self.current_pos = (0, 0)  # 현재 마우스 위치 (캔버스 좌표)


def ask_question_num():
    while True:
        raw = input("  문항번호를 입력하세요 (정수): ").strip()
        try:
            return int(raw)
        except ValueError:
            print("  다시 입력하세요. (정수를 입력해야 합니다)")


def build_canvas(img):
    """이미지를 고정 크기 캔버스 안에 비율 유지하며 맞추고, 스케일/오프셋을 반환."""
    orig_h, orig_w = img.shape[:2]
    scale = min(CANVAS_W / orig_w, CANVAS_H / orig_h, 1.0)
    disp_w, disp_h = max(1, int(orig_w * scale)), max(1, int(orig_h * scale))
    resized = cv2.resize(img, (disp_w, disp_h)) if scale != 1.0 else img.copy()

    canvas = np.full((CANVAS_H, CANVAS_W, 3), PAD_COLOR, dtype=np.uint8)
    off_x = (CANVAS_W - disp_w) // 2
    off_y = (CANVAS_H - disp_h) // 2
    canvas[off_y:off_y + disp_h, off_x:off_x + disp_w] = resized

    return canvas, scale, off_x, off_y


def process_image(path: Path, idx: int, total: int):
    print(f"\n[{idx}/{total}] 진행 중... ({path.name})")

    img = imread_unicode(path)
    if img is None:
        print(f"  이미지를 열 수 없습니다: {path} -> 건너뜁니다.")
        return None

    orig_h, orig_w = img.shape[:2]
    base_canvas, scale, off_x, off_y = build_canvas(img)

    def to_original(cx, cy):
        ox = (cx - off_x) / scale
        oy = (cy - off_y) / scale
        return ox, oy

    state = ImageState()
    question_num = None

    def on_mouse(event, x, y, flags, param):
        state.current_pos = (x, y)

        if event == cv2.EVENT_LBUTTONDOWN:
            state.drag_start = (x, y)
            state.dragging = True

        elif event == cv2.EVENT_LBUTTONUP:
            if state.drag_start is None:
                return
            sx, sy = state.drag_start
            ex, ey = x, y
            state.dragging = False
            state.drag_start = None

            if state.mode == "point":
                ox_f, oy_f = to_original(ex, ey)
                ox, oy = int(round(ox_f)), int(round(oy_f))
                if not (0 < ox < orig_w and 0 < oy < orig_h):
                    print("  이미지 바깥을 클릭했습니다. 다시 입력하세요.")
                    return
                state.point = (ox, oy)
                print(f"  손끝 좌표 기록: ({ox}, {oy})")

            elif state.mode == "bbox":
                sx_o, sy_o = to_original(sx, sy)
                ex_o, ey_o = to_original(ex, ey)
                x_min = clamp(int(round(min(sx_o, ex_o))), 0, orig_w - 1)
                x_max = clamp(int(round(max(sx_o, ex_o))), 0, orig_w - 1)
                y_min = clamp(int(round(min(sy_o, ey_o))), 0, orig_h - 1)
                y_max = clamp(int(round(max(sy_o, ey_o))), 0, orig_h - 1)
                if x_max - x_min < 3 or y_max - y_min < 3:
                    print("  바운딩박스가 너무 작습니다. 다시 입력하세요.")
                    return
                state.bbox = (x_min, y_min, x_max, y_max)
                print(f"  바운딩박스 기록: {state.bbox} (Enter로 확정, r로 다시 그리기)")

    cv2.setMouseCallback(WINDOW_NAME, on_mouse)
    print("  마우스로 손끝 위치를 클릭하세요.")

    result = None
    while True:
        frame = base_canvas.copy()

        if state.point is not None:
            px = int(off_x + state.point[0] * scale)
            py = int(off_y + state.point[1] * scale)
            cv2.circle(frame, (px, py), 6, (0, 255, 0), -1)

        if state.bbox is not None:
            x_min, y_min, x_max, y_max = state.bbox
            p1 = (int(off_x + x_min * scale), int(off_y + y_min * scale))
            p2 = (int(off_x + x_max * scale), int(off_y + y_max * scale))
            cv2.rectangle(frame, p1, p2, (0, 0, 255), 2)

        if state.dragging and state.drag_start is not None:
            cv2.rectangle(frame, state.drag_start, state.current_pos, (0, 0, 255), 1)

        status = f"[{idx}/{total}] {path.name} | mode={state.mode}"
        if question_num is not None:
            status += f" | Q{question_num}"
        cv2.putText(frame, status, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
        cv2.imshow(WINDOW_NAME, frame)

        key = cv2.waitKey(20) & 0xFF

        if state.mode == "point" and state.point is not None:
            question_num = ask_question_num()
            state.mode = "bbox"
            print("  이제 마우스 드래그로 바운딩박스를 그리세요.")

        if key == ord('r'):
            if state.mode == "bbox":
                state.bbox = None
                print("  바운딩박스를 다시 그려주세요.")
            else:
                state.point = None
                print("  손끝 좌표를 다시 클릭하세요.")

        elif key in (13, 10):  # Enter
            if state.point is None:
                print("  손끝 좌표를 먼저 클릭하세요.")
            elif question_num is None:
                pass
            elif state.bbox is None:
                print("  바운딩박스를 먼저 드래그로 그리세요.")
            else:
                x, y = state.point
                x_min, y_min, x_max, y_max = state.bbox
                result = {
                    "x": x,
                    "y": y,
                    "question_num": question_num,
                    "bbox": {
                        "x_min": x_min,
                        "y_min": y_min,
                        "x_max": x_max,
                        "y_max": y_max,
                    },
                }
                break

        elif key == 27:  # ESC
            result = "ABORT"
            break

    return result


def load_existing_results():
    if OUTPUT_PATH.exists():
        with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_results(results):
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


def main():
    if not IMAGE_DIR.exists():
        IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    image_paths = sorted(
        {p for p in IMAGE_DIR.iterdir() if p.suffix.lower() == ".jpg"},
        key=lambda p: p.name,
    )
    total = len(image_paths)
    if total == 0:
        print(f"{IMAGE_DIR} 안에 jpg 파일이 없습니다. testimage 폴더에 사진을 넣고 다시 실행하세요.")
        return

    results = load_existing_results()
    if results:
        print(f"기존 저장 파일을 불러왔습니다: {len(results)}개 완료됨. 이어서 진행합니다.")

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_AUTOSIZE)
    cv2.moveWindow(WINDOW_NAME, *WINDOW_POS)

    for idx, path in enumerate(image_paths, start=1):
        if path.name in results:
            print(f"[{idx}/{total}] {path.name} 은 이미 완료됨. 건너뜁니다.")
            continue

        entry = process_image(path, idx, total)

        if entry == "ABORT":
            print("\n사용자에 의해 중단되었습니다. 지금까지 결과를 저장합니다.")
            break
        if entry is None:
            continue

        results[path.name] = entry
        save_results(results)
        print(f"[{idx}/{total}] 저장 완료 -> {OUTPUT_PATH.name}")

    cv2.destroyAllWindows()
    print(f"\n총 {len(results)}/{total}개 완료. 결과 파일: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
