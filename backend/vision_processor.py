import cv2
import sys
import json
import base64
import os
import math
import numpy as np


def _blur_score(gray):
    """
    흐림 점수 (Laplacian 분산).
    여백·해상도 영향을 줄이기 위해 긴 변을 1000px로 리사이즈한 뒤 측정한다.
    (글자가 선명하면 여백이 많아도 점수가 안정적으로 나옴)
    """
    h, w = gray.shape[:2]
    long_side = max(h, w)
    if long_side > 1000:
        scale = 1000.0 / long_side
        gray = cv2.resize(gray, (int(w * scale), int(h * scale)))
    return cv2.Laplacian(gray, cv2.CV_64F).var()


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

    # 1. 흐림 체크 (리사이즈 후 측정 → 여백 영향 완화)
    blur_score = _blur_score(gray)
    if blur_score < 500:
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


# -------------------------------------------------------------
# 손가락 검출 헬퍼: 종이 마스크 / 피부색 마스크
# -------------------------------------------------------------
def _find_paper_mask(img):
    """흰 문제지 영역 마스크 (밝고 채도 낮은 픽셀 = 종이). 가장 큰 덩어리만 채워서 반환."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    paper = cv2.inRange(hsv, np.array([0, 0, 120]), np.array([180, 70, 255]))
    k = np.ones((15, 15), np.uint8)
    paper = cv2.morphologyEx(paper, cv2.MORPH_CLOSE, k)
    paper = cv2.morphologyEx(paper, cv2.MORPH_OPEN, k)
    cnts, _ = cv2.findContours(paper, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if cnts:
        big = max(cnts, key=cv2.contourArea)
        clean = np.zeros_like(paper)
        cv2.drawContours(clean, [big], -1, 255, -1)
        paper = clean
    return paper


def _find_skin_mask(img, sat_min):
    """피부색 마스크 (기존과 동일 HSV 범위)."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    return cv2.inRange(hsv, np.array([0, sat_min, 80]), np.array([20, 170, 255]))


def find_finger_tip(img):
    """
    2단계: OpenCV로 검지 끝 좌표 추출 (종이-마스크 + 뾰족한 끝점).

    핵심 가정: '손가락 끝은 항상 흰 종이 위에 올라온다.'
      1) 흰 종이 영역을 먼저 찾는다.
      2) 살색이면서 종이 영역(약간 확장)에 들어온 부분만 = 손가락 (책상 제외).
      3) 손가락 덩어리의 '무게중심에서 가장 멀리 뾰족하게 튀어나온 끝점' = 손끝.
         (손가락 사이 골/옆선이 아니라 실제 손톱 끝을 잡기 위함)

    손가락이 없으면 (None, "손가락 없음") 반환 (에러 아님).
    """
    h, w = img.shape[:2]
    sat_min = get_sat_min(img)

    paper = _find_paper_mask(img)
    skin = _find_skin_mask(img, sat_min)

    # 종이가 거의 안 잡히면 손가락 판단 불가 -> None
    if np.sum(paper > 0) < (h * w) * 0.05:
        return None, "손가락 없음"

    # 손가락 후보 = 살색 n 종이영역(확장). 종이 가장자리에 걸친 손가락까지 포함.
    k_big = np.ones((45, 45), np.uint8)
    paper_dil = cv2.dilate(paper, k_big)
    finger = cv2.bitwise_and(skin, paper_dil)

    # 종이 내부 깊숙한 영역(글자/그림 오검출 방지)은 제외
    paper_core = cv2.erode(paper, k_big)
    finger = cv2.bitwise_and(finger, cv2.bitwise_not(paper_core))

    # 덩어리화 (노이즈 제거 + 끊긴 부분 연결)
    finger = cv2.morphologyEx(finger, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    finger = cv2.morphologyEx(finger, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))

    cnts, _ = cv2.findContours(finger, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cnts = [c for c in cnts if cv2.contourArea(c) > (h * w) * 0.001]  # 잡티 제거
    if not cnts:
        return None, "손가락 없음"

    largest = max(cnts, key=cv2.contourArea)

    tip_x, tip_y = _find_pointed_tip(largest, paper)
    if tip_x is None:
        return None, "손가락 없음"

    # corner: 손끝이 이미지의 어느 사분면에서 들어왔는지 (참고용)
    vert = "top" if tip_y < h / 2 else "bottom"
    horiz = "left" if tip_x < w / 2 else "right"
    corner = "%s_%s" % (vert, horiz)

    return {"x": int(tip_x), "y": int(tip_y), "corner": corner}, "OK"


def _find_pointed_tip(contour, paper):
    """
    손가락 덩어리에서 '실제 손끝'을 찾는다.
      - 손이 종이로 들어오는 '뿌리(손목 쪽)' 의 반대편,
        즉 종이 안쪽으로 가장 뾰족하게 뻗은 점을 끝으로 본다.
      - 손가락 사이 골짜기(오목한 부분)는 무게중심 기준 '먼 볼록점'이 아니므로 걸러진다.
    """
    pts = contour.reshape(-1, 2)
    if len(pts) < 3:
        return None, None

    # 손 덩어리 무게중심
    M = cv2.moments(contour)
    if M["m00"] == 0:
        return None, None
    gx, gy = M["m10"] / M["m00"], M["m01"] / M["m00"]

    # 종이 중심 (손끝은 종이 중심 쪽을 향한다)
    Mp = cv2.moments(paper)
    if Mp["m00"] == 0:
        px, py = paper.shape[1] / 2, paper.shape[0] / 2
    else:
        px, py = Mp["m10"] / Mp["m00"], Mp["m01"] / Mp["m00"]

    # 손 무게중심 -> 종이 중심 방향 벡터 (손가락이 가리키는 방향)
    dx, dy = px - gx, py - gy
    norm = (dx * dx + dy * dy) ** 0.5
    if norm < 1e-6:
        dx, dy = 0, -1
    else:
        dx, dy = dx / norm, dy / norm

    # 외곽선 각 점을 '가리키는 방향'으로 투영 → 가장 멀리 뻗은 점 = 손끝
    proj = (pts[:, 0] - gx) * dx + (pts[:, 1] - gy) * dy
    idx = int(proj.argmax())
    return int(pts[idx][0]), int(pts[idx][1])


# -------------------------------------------------------------
# 손끝 좌표 -> 문제 블록 crop
# -------------------------------------------------------------
def _row_projection_blocks(row_sum, y_top, y_bottom, ink_threshold=3, min_gap_px=15):
    """
    row_sum(가로줄별 잉크 픽셀 수)에서 min_gap_px 이상 연속으로
    ink_threshold 이하인 여백 구간을 구분선으로 삼아,
    [y_top, y_bottom) 구간을 문제 블록 단위 (y_start, y_end) 리스트로 분할한다.
    """
    blocks = []
    block_start = None
    blank_run = 0

    for y in range(y_top, y_bottom):
        if row_sum[y] <= ink_threshold:
            blank_run += 1
            if blank_run >= min_gap_px and block_start is not None:
                blocks.append((block_start, y - blank_run + 1))
                block_start = None
        else:
            if block_start is None:
                block_start = y
            blank_run = 0

    if block_start is not None:
        blocks.append((block_start, y_bottom))

    return blocks


def _detect_vertical_lines(img, paper, canny_low=50, canny_high=150,
                            hough_threshold=50, min_segment_len=150, max_line_gap=30,
                            angle_tol_deg=15):
    """
    Hough Line Transform으로 종이 영역 안에서 거의 수직인 직선 조각(세그먼트)을 모두 찾는다.

    휴대폰으로 찍은 문제지는 종이가 살짝 휘어 있는 경우가 많아서, 컬럼 구분선이
    한 번에 긴 직선 하나로 안 잡히고 여러 개의 짧은 세그먼트로 끊겨서 검출된다.
    그래서 여기서는 세그먼트를 전부 모아서 반환만 하고, 위치별로 묶어서 하나의
    구분선으로 판단하는 건 _find_vertical_divider_line에서 한다.

    반환: [(x_mid, length, (x1, y1, x2, y2)), ...]
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, canny_low, canny_high)
    edges = cv2.bitwise_and(edges, paper)

    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 180,
        threshold=hough_threshold,
        minLineLength=min_segment_len,
        maxLineGap=max_line_gap,
    )
    if lines is None:
        return []

    segments = []
    # cv2.HoughLinesP의 반환 shape은 OpenCV 버전에 따라 (N, 1, 4) 또는 (N, 4)로 달라진다.
    # lines[:, 0]은 (N, 4)인 경우 각 행이 아니라 첫 열(x1 스칼라들)만 뽑아버려 언패킹이
    # 깨지므로, reshape(-1, 4)로 두 shape 모두에서 항상 (N, 4)가 되도록 정규화한다.
    for x1, y1, x2, y2 in lines.reshape(-1, 4):
        dx, dy = int(x2) - int(x1), int(y2) - int(y1)
        length = math.hypot(dx, dy)
        angle = abs(math.degrees(math.atan2(dy, dx)))
        angle = min(angle, 180 - angle)
        if angle < 90 - angle_tol_deg:
            continue
        segments.append(((x1 + x2) / 2, length, (int(x1), int(y1), int(x2), int(y2))))

    return segments


def _find_vertical_divider_line(img, paper, x_left, x_right, margin_ratio=0.08,
                                 cluster_gap_px=60, min_total_length_ratio=0.5):
    """
    _detect_vertical_lines가 찾은 세그먼트들을 x좌표 기준으로 묶어(clustering),
    총 길이가 가장 긴 클러스터를 '컬럼 구분선'으로 채택한다.

    (하나의 최장 직선을 찾는 대신 끊긴 세그먼트들의 길이를 합산하는 방식이라
    종이가 휘어서 한 번에 긴 직선으로 안 잡혀도 잘 찾아낸다)

    종이 자체의 좌우 가장자리(margin_ratio 안쪽만 검색)는 제외한다 —
    안 그러면 종이 테두리 자체가 구분선으로 오검출될 수 있다.

    채택된 클러스터의 총 길이가 min_total_length_ratio * 이미지 높이에 못 미치면
    (진짜 구분선이라기엔 근거가 약하다고 보고) None을 반환한다.
    """
    h = img.shape[0]
    segments = _detect_vertical_lines(img, paper)
    if not segments:
        return None

    paper_width = x_right - x_left
    search_start = x_left + int(paper_width * margin_ratio)
    search_end = x_right - int(paper_width * margin_ratio)

    segments = [s for s in segments if search_start <= s[0] <= search_end]
    if not segments:
        return None

    segments.sort(key=lambda s: s[0])
    clusters = [[segments[0]]]
    for seg in segments[1:]:
        if seg[0] - clusters[-1][-1][0] <= cluster_gap_px:
            clusters[-1].append(seg)
        else:
            clusters.append([seg])

    best_x, best_total = None, 0
    for cluster in clusters:
        total = sum(s[1] for s in cluster)
        if total > best_total:
            best_total = total
            best_x = sum(s[0] * s[1] for s in cluster) / total

    if best_x is None or best_total < h * min_total_length_ratio:
        return None

    return best_x


def _find_column_bounds(img, ink_threshold=3, min_gap_px_x=20, margin_ratio=0.08,
                         min_total_length_ratio=0.5):
    """
    문제지가 좌/우 2단 컬럼인지 확인하고 컬럼 경계를 나눈다. 우선순위:

      1) Hough Line Transform으로 종이 안에서 세로로 길게 이어지는 인쇄선(구분선)을 찾는다.
         (예: image/16.jpg처럼 컬럼 사이가 빈 여백이 아니라 굵은 세로선으로 나뉜 경우,
          빈 구간을 찾는 방식으로는 애초에 구분선을 못 찾는다)
      2) 못 찾으면 column projection(빈 여백 탐색) 방식으로 폴백한다.
      3) 그것도 못 찾으면 1단 문제지로 간주하고 종이 전체 범위를 그대로 반환한다.

    2단이면 [(왼쪽 x_start, x_end), (오른쪽 x_start, x_end)] 2개를,
    끝내 구분선을 못 찾으면(1단 문제지로 간주) [(종이 전체 x_start, x_end)] 1개를 반환한다.
    """
    _, w = img.shape[:2]
    paper = _find_paper_mask(img)

    paper_cols = np.where(np.sum(paper > 0, axis=0) > 0)[0]
    if len(paper_cols) == 0:
        return [(0, w)]
    x_left, x_right = int(paper_cols[0]), int(paper_cols[-1]) + 1

    # 1) Hough Line 기반 구분선 탐색
    divider_x = _find_vertical_divider_line(
        img, paper, x_left, x_right, margin_ratio, min_total_length_ratio=min_total_length_ratio
    )
    if divider_x is not None:
        return [(x_left, int(divider_x)), (int(divider_x), x_right)]

    # 2) column projection(빈 여백) 폴백
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    binary = cv2.bitwise_and(binary, paper)
    col_sum = np.sum(binary > 0, axis=0)

    paper_width = x_right - x_left
    search_start = x_left + int(paper_width * margin_ratio)
    search_end = x_right - int(paper_width * margin_ratio)

    gap_runs = []
    run_start = None
    for x in range(search_start, search_end):
        if col_sum[x] <= ink_threshold:
            if run_start is None:
                run_start = x
        else:
            if run_start is not None and x - run_start >= min_gap_px_x:
                gap_runs.append((run_start, x))
            run_start = None
    if run_start is not None and search_end - run_start >= min_gap_px_x:
        gap_runs.append((run_start, search_end))

    if gap_runs:
        center = (x_left + x_right) / 2
        gap_start, gap_end = min(gap_runs, key=lambda g: abs((g[0] + g[1]) / 2 - center))
        return [(x_left, gap_start), (gap_end, x_right)]

    # 3) 1단 문제지로 간주
    return [(x_left, x_right)]


def compute_crop_bounds(img, x, y, padding=120, padding_x=180, ink_threshold=3, min_gap_px=15,
                         min_gap_px_x=20, margin_ratio=0.08, min_total_length_ratio=0.5):
    """
    crop_pointed_question이 사용할 (x_start, y_start, x_end, y_end)만 계산해서 반환한다.
    crop_pointed_question에서 분리해둔 이유: 파이프라인 쪽에서 "손끝이 crop 영역 안
    어디쯤인지" 같은 걸 같은 경계값 기준으로 계산하려면 이 값이 따로 필요하기 때문
    (crop_pointed_question 자체의 동작/반환값은 그대로).

    로직은 이전 crop_pointed_question과 동일:
      1) _find_column_bounds로 좌/우 컬럼(2단 문제지) 또는 전체(1단 문제지)를 나눈다.
         (Hough Line으로 인쇄된 구분선을 먼저 찾고, 못 찾으면 빈 여백 탐색으로 폴백)
      2) x가 속한 컬럼을 고른다 (어느 컬럼에도 안 걸치면 가장 가까운 컬럼으로 폴백).
      3) 그 컬럼 영역만 이진화(Otsu)해서 글자(잉크) 픽셀만 남긴다.
      4) 가로줄(row)별 잉크 픽셀 합(row projection)을 구해서,
         여백이 min_gap_px 이상 연속되는 지점을 문제 사이 구분선으로 보고 블록으로 나눈다.
      5) y가 속한 블록을 찾아 위아래 padding, 컬럼 좌우로 padding_x를 더 여유 있게 붙인다.

    블록을 못 찾으면 None을 반환한다.
    """
    h, w = img.shape[:2]
    paper = _find_paper_mask(img)

    if np.sum(paper > 0) < (h * w) * 0.05:
        return None

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    binary = cv2.bitwise_and(binary, paper)

    columns = _find_column_bounds(img, ink_threshold, min_gap_px_x, margin_ratio, min_total_length_ratio)

    col = None
    for cx_start, cx_end in columns:
        if cx_start <= x <= cx_end:
            col = (cx_start, cx_end)
            break
    if col is None:
        col = min(columns, key=lambda c: min(abs(x - c[0]), abs(x - c[1])))

    cx_start, cx_end = col
    paper_col = paper[:, cx_start:cx_end]
    binary_col = binary[:, cx_start:cx_end]

    paper_rows = np.where(np.sum(paper_col > 0, axis=1) > 0)[0]
    if len(paper_rows) == 0:
        return None
    y_top, y_bottom = int(paper_rows[0]), int(paper_rows[-1]) + 1

    row_sum = np.sum(binary_col > 0, axis=1)
    blocks = _row_projection_blocks(row_sum, y_top, y_bottom, ink_threshold, min_gap_px)

    if not blocks:
        return None

    target = None
    for y_start, y_end in blocks:
        if y_start <= y <= y_end:
            target = (y_start, y_end)
            break
    if target is None:
        # 손끝이 두 블록 사이 여백에 걸친 경우 (예: 문제 제목과 내용/보기가 여백을 사이에
        # 두고 서로 다른 블록으로 쪼개진 경우) -> 가장 가까운 블록 하나만 고르면 제목이나
        # 보기 중 한쪽이 통째로 잘려나갈 수 있다. 그래서 앞뒤 블록을 합쳐서 아무것도
        # 안 잘리게 한다 (범위가 넓어지는 건 감수 - 문맥 이해는 Gemini 몫).
        prev_block = max((b for b in blocks if b[1] <= y), key=lambda b: b[1], default=None)
        next_block = min((b for b in blocks if b[0] >= y), key=lambda b: b[0], default=None)
        if prev_block and next_block:
            target = (prev_block[0], next_block[1])
        else:
            target = prev_block or next_block

    y_start, y_end = target
    y_start = max(0, y_start - padding)
    y_end = min(h, y_end + padding)

    x_start = max(0, cx_start - padding_x)
    x_end = min(w, cx_end + padding_x)

    return x_start, y_start, x_end, y_end


def crop_pointed_question(img, x, y, padding=120, padding_x=180, ink_threshold=3, min_gap_px=15,
                           min_gap_px_x=20, margin_ratio=0.08, min_total_length_ratio=0.5):
    """
    3단계: find_finger_tip이 찾은 손끝 좌표 (x, y) 주변 '문제 한 덩어리'만 crop.
    경계 계산은 compute_crop_bounds가 한다 (로직 설명은 그쪽 docstring 참고).

    블록을 못 찾으면 None을 반환한다 (호출부에서 원본 이미지로 폴백해야 함).
    """
    bounds = compute_crop_bounds(img, x, y, padding, padding_x, ink_threshold, min_gap_px,
                                  min_gap_px_x, margin_ratio, min_total_length_ratio)
    if bounds is None:
        return None

    x_start, y_start, x_end, y_end = bounds
    return img[y_start:y_end, x_start:x_end].copy()


def debug_visualize_blocks(img, x=None, y=None, padding=120, ink_threshold=3, min_gap_px=15,
                            min_gap_px_x=20, margin_ratio=0.08, save_path=None):
    """
    crop_pointed_question와 같은 로직(컬럼 분리 -> 선택된 컬럼에서 row projection)으로
    계산한 뒤,
      - 원본 이미지에 컬럼 경계선(주황) / 블록 경계선(초록) / 선택된 블록+padding(파랑 박스) / 입력 좌표(빨간 점)
      - 선택된 컬럼의 row projection 그래프(오른쪽)
    를 나란히 그려서 확인하는 디버그 전용 함수.
    matplotlib이 필요하며 requirements.txt에는 포함되어 있지 않다 (디버그용이라 별도 설치 필요).

    save_path를 주면 파일로 저장하고, 없으면 plt.show()로 화면에 띄운다.
    """
    import matplotlib.pyplot as plt

    h, _ = img.shape[:2]
    paper = _find_paper_mask(img)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    binary = cv2.bitwise_and(binary, paper)

    columns = _find_column_bounds(img, ink_threshold, min_gap_px_x, margin_ratio)

    col = columns[0]
    if x is not None:
        for cx_start, cx_end in columns:
            if cx_start <= x <= cx_end:
                col = (cx_start, cx_end)
                break
        else:
            col = min(columns, key=lambda c: min(abs(x - c[0]), abs(x - c[1])))

    cx_start, cx_end = col
    paper_col = paper[:, cx_start:cx_end]
    binary_col = binary[:, cx_start:cx_end]

    paper_rows = np.where(np.sum(paper_col > 0, axis=1) > 0)[0]
    y_top, y_bottom = (int(paper_rows[0]), int(paper_rows[-1]) + 1) if len(paper_rows) else (0, h)

    row_sum = np.sum(binary_col > 0, axis=1)
    blocks = _row_projection_blocks(row_sum, y_top, y_bottom, ink_threshold, min_gap_px)

    vis = img.copy()
    for cx_s, cx_e in columns:
        cv2.line(vis, (cx_s, 0), (cx_s, h), (0, 165, 255), 2)
        cv2.line(vis, (cx_e, 0), (cx_e, h), (0, 165, 255), 2)

    for y_start, y_end in blocks:
        cv2.line(vis, (cx_start, y_start), (cx_end, y_start), (0, 255, 0), 2)
        cv2.line(vis, (cx_start, y_end), (cx_end, y_end), (0, 255, 0), 2)

    if y is not None:
        for y_start, y_end in blocks:
            if y_start <= y <= y_end:
                ys, ye = max(0, y_start - padding), min(h, y_end + padding)
                cv2.rectangle(vis, (cx_start, ys), (cx_end, ye), (255, 0, 0), 3)
                break
        if x is not None:
            cv2.circle(vis, (int(x), int(y)), 10, (0, 0, 255), -1)

    fig, (ax_img, ax_proj) = plt.subplots(1, 2, figsize=(14, 8), gridspec_kw={"width_ratios": [2, 1]})

    ax_img.imshow(cv2.cvtColor(vis, cv2.COLOR_BGR2RGB))
    ax_img.set_title("columns(orange) / blocks(green) / selected+padding(blue) / point(red)")
    ax_img.axis("off")

    ax_proj.plot(row_sum, np.arange(h))
    ax_proj.axvline(ink_threshold, color="gray", linestyle="--", label="ink_threshold")
    for y_start, y_end in blocks:
        ax_proj.axhline(y_start, color="green", linewidth=0.8)
        ax_proj.axhline(y_end, color="green", linewidth=0.8)
    if y is not None:
        ax_proj.axhline(y, color="red", linewidth=1)
    ax_proj.invert_yaxis()
    ax_proj.set_xlabel("ink pixel count (selected column)")
    ax_proj.set_ylabel("row (y)")
    ax_proj.set_title("row projection (selected column)")
    ax_proj.legend(loc="upper right", fontsize=8)

    plt.tight_layout()
    if save_path:
        plt.savefig(save_path)
        plt.close(fig)
    else:
        plt.show()


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
        blur_score = round(_blur_score(gray), 1)
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