"""
기울기 보정(Deskewing) - 살짝(수 도) 기운 사진을 수평으로 편다.

app/orientation.py가 90° 단위로 누운 사진을 세운 뒤, 남은 작은 기울기를 여기서 잡는다.
기울어진 줄은 축에 평행한 줄 박스(bbox)가 위아래로 부풀어서 옆 줄·옆 문항과 겹친다
(실측 사례: 227.jpg - 7번 발문 줄 박스가 기울기 때문에 6번 보기 쪽까지 올라옴).

  기울기 측정: estimate_skew_hough (OpenCV - 글자를 가로로 이어붙여 줄 덩어리로 만든 뒤
              cv2.HoughLinesP로 직선 각도의 중앙값) / estimate_skew_ocr (Clova 단어 좌표로
              줄마다 기울기를 직선 근사한 중앙값)
  펴기:       cv2.getRotationMatrix2D + cv2.warpAffine (사진), cv2.transform (Clova 단어
              꼭짓점·손끝 좌표에 같은 행렬 적용) → Clova 재호출 없음

단어 꼭짓점을 돌린 뒤 줄을 다시 묶어야(to_lines) 줄 박스가 납작하게 펴진다. 이미 만든 줄
박스를 돌리면 오히려 더 커진다.

서비스(pipeline.py)는 OCR 방식으로 각도를 재고 OpenCV로 편다. 415장을 인위적으로 5/10/15도
기울여 비교한 결과(2026-10-09): 보정 없음 96.1/93.9/89.0% → OCR 96.8/96.8/96.8%, Hough
96.8/96.6/96.3%. Hough는 긴 직선이 부족한 사진 38장에서 각도 측정 자체를 실패해서 OCR 방식을
채택하고, estimate_skew_hough는 비교·발표용으로 남겨둔다. 테스트 사진은 대부분 똑바로 찍혀
(기울기 중앙값 1.0도) 원본 그대로는 효과가 1장(101.jpg)뿐이었지만, 실사용자가 비스듬히 찍는
경우를 대비한 장치다.

각도 부호: 이미지 좌표(y 아래로 증가)에서 줄이 오른쪽으로 갈수록 내려가면 양수.
"""
import copy

import cv2
import numpy as np

# 이 각도(도)보다 작으면 펴지 않는다 / 이보다 크면 측정 오류로 보고 펴지 않는다
MIN_SKEW_DEG = 1.0
MAX_SKEW_DEG = 20.0


def estimate_skew_hough(img) -> float | None:
    """OpenCV로 기울기 측정. 측정할 직선이 부족하면 None."""
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # 글자(어두운 부분) = 흰색인 이진 마스크
    ink = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 15)
    # 가로로 긴 커널로 닫으면 한 줄의 글자들이 하나의 가로 띠로 이어진다
    band = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (max(15, w // 40), 1)))
    edges = cv2.Canny(band, 50, 150)
    segs = cv2.HoughLinesP(edges, 1, np.pi / 720, threshold=80,
                           minLineLength=int(w * 0.15), maxLineGap=10)
    if segs is None:
        return None
    angles, weights = [], []
    for x1, y1, x2, y2 in segs.reshape(-1, 4):
        if x2 == x1:
            continue
        a = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        if a > 90:
            a -= 180
        elif a < -90:
            a += 180
        if abs(a) <= MAX_SKEW_DEG:
            angles.append(a)
            weights.append(np.hypot(x2 - x1, y2 - y1))
    if len(angles) < 5:
        return None
    # 길이 가중 중앙값
    order = np.argsort(angles)
    a, wt = np.array(angles)[order], np.array(weights)[order]
    return float(a[np.searchsorted(np.cumsum(wt), wt.sum() / 2)])


def estimate_skew_ocr(response: dict) -> float | None:
    """Clova 단어 좌표로 기울기 측정 (줄마다 단어 중심점을 직선 근사한 기울기의 중앙값)."""
    images = response.get("images") or []
    fields = (images[0].get("fields") or []) if images else []
    angles, cur = [], []
    for f in fields:
        v = f["boundingPoly"]["vertices"]
        cur.append((sum(p["x"] for p in v) / len(v), sum(p["y"] for p in v) / len(v)))
        if f.get("lineBreak"):
            if len(cur) >= 4:
                xs, ys = np.array(cur).T
                if xs.max() - xs.min() > 150:
                    angles.append(np.degrees(np.arctan(np.polyfit(xs, ys, 1)[0])))
            cur = []
    return float(np.median(angles)) if len(angles) >= 3 else None


def deskew_matrix(angle: float, w: int, h: int):
    """angle(도)만큼 기운 사진을 펴는 2x3 행렬과 펴진 사진 크기. 모서리가 잘리지 않게 캔버스를 넓힌다."""
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    cos, sin = abs(M[0, 0]), abs(M[0, 1])
    nw, nh = int(round(h * sin + w * cos)), int(round(h * cos + w * sin))
    M[0, 2] += nw / 2 - w / 2
    M[1, 2] += nh / 2 - h / 2
    return M, nw, nh


def warp_image(img, M, nw, nh):
    return cv2.warpAffine(img, M, (nw, nh), flags=cv2.INTER_LINEAR, borderValue=(255, 255, 255))


def warp_point(x, y, M):
    p = cv2.transform(np.array([[[x, y]]], dtype=np.float64), M)[0, 0]
    return float(p[0]), float(p[1])


def warp_response(response: dict, M, nw, nh) -> dict:
    """Clova 응답의 모든 단어 꼭짓점에 행렬을 적용한 복사본 (to_lines에 그대로 넣을 수 있음)."""
    out = copy.deepcopy(response)
    im = out["images"][0]
    for f in im.get("fields") or []:
        verts = f["boundingPoly"]["vertices"]
        pts = cv2.transform(np.array([[[v["x"], v["y"]] for v in verts]], dtype=np.float64), M)[0]
        for v, (x, y) in zip(verts, pts):
            v["x"], v["y"] = float(x), float(y)
    im["convertedImageInfo"] = {**(im.get("convertedImageInfo") or {}), "width": nw, "height": nh}
    return out
