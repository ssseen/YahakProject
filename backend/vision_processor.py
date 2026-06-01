import cv2
import sys
import json
import base64
import os
import numpy as np

def get_sat_min(img):
    """밝기에 따라 피부색 채도 기준 동적 조정"""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    brightness = gray.mean()
    if brightness < 80:
        return 30
    elif brightness < 130:
        return 60
    else:
        return 70

def check_image_quality(img):
    """1단계: 이미지 사용성 검증"""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = img.shape[:2]
    total_area = h * w

    # 1. 흐림 체크
    blur_score = cv2.Laplacian(gray, cv2.CV_64F).var()
    if blur_score < 60:
        return False, "사진이 너무 흔들렸어요. 다시 촬영해주세요", blur_score

    # 2. 밝기 체크
    brightness = round(float(gray.mean()), 1)
    if brightness < 40:
        return False, "너무 어두워요. 밝은 곳에서 촬영해주세요", blur_score
    if brightness > 220:
        return False, "너무 밝아요. 빛을 피해 촬영해주세요", blur_score

    # 3. 글자 인식 가능 여부
    edges = cv2.Canny(gray, 80, 200)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    text_like = 0
    for c in contours:
        area = cv2.contourArea(c)
        if 100 < area < total_area * 0.005:
            x, y, cw, ch = cv2.boundingRect(c)
            ratio = cw / max(ch, 1)
            if 0.5 < ratio < 10:
                text_like += 1

    if text_like < 20:
        return False, "글자가 잘 보이지 않아요. 문제지를 정면으로 촬영해주세요", blur_score

    return True, "OK", blur_score

def find_finger_tip(img):
    """2단계: OpenCV로 검지 끝 좌표 추출"""
    h, w = img.shape[:2]
    sat_min = get_sat_min(img)

    # 모서리별 탐색 영역 + 끝점 방향 정의
    corners = {
        "top_left":     {"region": (0,           int(h*0.25), 0,           int(w*0.25)), "tip": "max_x_plus_y"},
        "top_right":    {"region": (0,           int(h*0.25), int(w*0.75), w),           "tip": "max_y_minus_x"},
        "bottom_left":  {"region": (int(h*0.75), h,           0,           int(w*0.25)), "tip": "max_x_minus_y"},
        "bottom_right": {"region": (int(h*0.75), h,           int(w*0.75), w),           "tip": "min_x_plus_y"},
    }

    best_corner = None
    best_ratio = 0

    for name, info in corners.items():
        y1, y2, x1, x2 = info["region"]
        roi = img[y1:y2, x1:x2]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array([0, sat_min, 80]), np.array([20, 170, 255]))
        ratio = np.sum(mask > 0) / (mask.shape[0] * mask.shape[1])
        if ratio > best_ratio:
            best_ratio = ratio
            best_corner = name

    # 피부색 비율 10% 미만 = 손가락 없음 → 그냥 None 반환 (에러 아님)
    if best_ratio < 0.1:
        return None, "손가락 없음"

    info = corners[best_corner]
    y1, y2, x1, x2 = info["region"]
    tip_dir = info["tip"]

    roi = img[y1:y2, x1:x2]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([0, sat_min, 80]), np.array([20, 170, 255]))

    kernel = np.ones((9, 9), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None, "손가락 없음"

    largest = max(contours, key=cv2.contourArea)
    pts = largest[:, :, :]

    # 모서리 방향에 따라 끝점 계산
    if tip_dir == "max_x_plus_y":
        idx = (pts[:, :, 0] + pts[:, :, 1]).argmax()
    elif tip_dir == "max_y_minus_x":
        idx = (pts[:, :, 1] - pts[:, :, 0]).argmax()
    elif tip_dir == "max_x_minus_y":
        idx = (pts[:, :, 0] - pts[:, :, 1]).argmax()
    else:
        idx = (pts[:, :, 0] + pts[:, :, 1]).argmin()

    tip = tuple(largest[idx][0])
    abs_x = int(tip[0]) + x1
    abs_y = int(tip[1]) + y1

    return {"x": abs_x, "y": abs_y, "corner": best_corner}, "OK"

def analyze_image(base64_string):
    try:
        if 'base64,' in base64_string:
            base64_string = base64_string.split(',')[1]
        img_data = base64.b64decode(base64_string)
        nparr = np.frombuffer(img_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return {"status": "error", "message": "이미지 디코딩 실패"}

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blur_score = round(cv2.Laplacian(gray, cv2.CV_64F).var(), 1)
        brightness = round(float(gray.mean()), 1)

        # 1단계: 품질 검증
        ok, msg, _ = check_image_quality(img)
        if not ok:
            return {
                "status": "retake",
                "message": msg,
                "blur_score": blur_score,
                "brightness": brightness
            }

        # 2단계: 좌표 추출 (없어도 success)
        tip, _ = find_finger_tip(img)

        return {
            "status": "success",
            "method": "OpenCV",
            "finger_detected": tip is not None,
            "x": tip["x"] if tip else None,
            "y": tip["y"] if tip else None,
            "corner": tip["corner"] if tip else None,
            "blur_score": blur_score,
            "brightness": brightness
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import sys
    base64_string = sys.stdin.read().strip()
    if base64_string:
        result = analyze_image(base64_string)
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(json.dumps({"status": "error", "message": "입력 없음"}, ensure_ascii=False))