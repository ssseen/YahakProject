"""
문항 영역 특정 — Clova 정규화 결과(lines)와 손끝 좌표로 "몇 번 문제인지"와
검색용 query_text / 마킹용 box를 계산한다.

담당 분리: 이 파일은 순수 좌표 산술 + 정규식이며 OpenCV를 쓰지 않는다.
Clova 파서(app/clova_client.py)는 별도 작업(P4)이며, 여기서는 이미
정규화된 Line 목록만 입력으로 받는다. 모든 좌표는 장축 1960px 기준.
"""
import bisect
import re
from dataclasses import dataclass, field
from statistics import median


ANCHOR = re.compile(r'^\s*(\d{1,2})\s*[.)]')
RANGE_HEADER = re.compile(r'^\[(\d+)\s*[~～\-]\s*(\d+)\]\s*(.+)')


class LocateError(Exception):
    """손끝 주변에서 문항을 특정할 수 있는 근거를 전혀 못 찾았을 때."""


@dataclass
class Line:
    text: str
    bbox: tuple[int, int, int, int]  # x1, y1, x2, y2


@dataclass
class LocateResult:
    question_number: int
    query_text: str
    box: tuple[int, int, int, int]
    range_header: str | None
    range_span: tuple[int, int] | None
    anchor_recovered: bool
    locate_confidence: str  # "high" | "low"
    fallback_level: int


@dataclass
class _Anchor:
    num: int
    top: int
    bottom_hint: int  # 밴드 상단 계산에만 쓰는 해당 줄의 y2 (참고용)
    recovered: bool = False


def _strip_anchor(text: str) -> str:
    return ANCHOR.sub('', text, count=1).strip()


def _rect_dist(bbox, px, py) -> float:
    x1, y1, x2, y2 = bbox
    dx = max(x1 - px, 0, px - x2)
    dy = max(y1 - py, 0, py - y2)
    return (dx * dx + dy * dy) ** 0.5


def _cluster_by_gap(values: list[float], gap: float) -> list[list[int]]:
    """
    오름차순 정렬 후 연속된 값끼리의 간격이 gap을 넘으면 새 그룹을 시작하는 체인
    클러스터링. 고정 기준점과의 절대 오차를 보는 방식과 달리 "직전 값과의 거리"만
    보므로, 페이지 전체에 걸쳐 완만하게 드리프트하는 값(예: 카메라 각도 때문에
    페이지 아래로 갈수록 서서히 밀리는 좌표)에도 강하다.
    반환: 원래 인덱스 기준 그룹 리스트, 그룹은 값 오름차순.
    """
    order = sorted(range(len(values)), key=lambda i: values[i])
    groups: list[list[int]] = []
    for oi in order:
        v = values[oi]
        if groups and v - values[groups[-1][-1]] <= gap:
            groups[-1].append(oi)
        else:
            groups.append([oi])
    return groups


def _find_anchor_candidates(lines: list[Line]):
    """전체 페이지(컬럼 구분 전)에서 번호 앵커 패턴에 매칭되는 줄을 전부 찾는다.
    반환: [(line_idx, num, x0), ...]"""
    out = []
    for i, l in enumerate(lines):
        m = ANCHOR.match(l.text)
        if m:
            out.append((i, int(m.group(1)), l.bbox[0]))
    return out


def _build_columns(lines: list[Line], gap: float):
    """
    앵커를 전체 페이지에서 먼저 찾고, 그 x0끼리만 체인 클러스터링해 컬럼의 좌측
    기준선을 정한 뒤, 모든 줄(앵커 포함)을 가장 가까운 기준선에 배정한다.

    "모든 줄을 먼저 x0로 뭉치고 그 안에서 앵커를 찾는" 이전 방식은 두 가지로 깨졌다:
      1) 카메라 각도 때문에 번호들의 왼쪽 x가 페이지 아래로 갈수록 서서히 밀리는데
         (실측 사례: 62px 드리프트), 고정 허용오차와 비교하는 방식이라 이 드리프트를
         못 버티고 번호 후보 자체가 탈락했다.
      2) 보기(①②③④)가 세로로 안 쌓이고 가로 격자로 넓게 흩어진 문제지에서는, 그
         격자 자체가 진짜 컬럼 경계처럼 오인식돼 번호 줄들이 엉뚱한 조각으로 쪼개졌다.

    앵커끼리만 먼저 체인 클러스터링하면 (1)은 절대오차가 아니라 연속값 간 간격만
    보므로 완만한 드리프트에 강하고, (2)는 애초에 보기 줄이 컬럼 판정 자체에
    관여하지 않으므로 발생하지 않는다.

    반환: [(col_left, [line_idx, ...]), ...] - 왼쪽→오른쪽 순서. 앵커가 전혀 없으면 빈 리스트.
    """
    anchor_candidates = _find_anchor_candidates(lines)
    if not anchor_candidates:
        return []

    x0s = [c[2] for c in anchor_candidates]
    groups = _cluster_by_gap(x0s, gap)

    col_lefts = sorted(min(anchor_candidates[gi][2] for gi in group) for group in groups)

    col_indices: list[list[int]] = [[] for _ in col_lefts]
    for i, l in enumerate(lines):
        x0 = l.bbox[0]
        # "가장 가까운 컬럼 기준선"(최근접 이웃)이 아니라 "내 x0 이하인 컬럼 중
        # 가장 오른쪽 것"으로 배정한다. 실측 사례: 보기가 격자로 넓게 퍼진 문제지에서
        # 왼쪽 컬럼 소속인 보기 하나(x0=992)가 오른쪽 컬럼(x0=1309)에 최근접이라는
        # 이유로 잘못 배정됐다 - 컬럼은 "그 지점부터 다음 컬럼이 시작되기 전까지"의
        # 영역이지, 기준선과의 거리로 나뉘는 게 아니다.
        pos = bisect.bisect_right(col_lefts, x0) - 1
        best = max(pos, 0)
        col_indices[best].append(i)

    return list(zip(col_lefts, col_indices))


def _find_range_header(lines: list[Line]):
    """RANGE_HEADER에 매칭되는 (start, end, body, line) 목록."""
    out = []
    for l in lines:
        m = RANGE_HEADER.match(l.text)
        if m:
            out.append((int(m.group(1)), int(m.group(2)), m.group(3).strip(), l))
    return out


def _build_anchors_for_column(col_indices: list[int], lines: list[Line], headers):
    """
    한 컬럼(이미 _build_columns가 배정한 줄 인덱스들) 안에서 앵커 후보(번호로
    시작하는 줄)를 찾고, 최장 증가 부분수열(LIS)로 오탐을 제거한 뒤, 결번이 있으면
    범위 지시문 힌트나 선형 보간으로 복구해 최종 앵커 리스트(y 오름차순)를 만든다.
    좌측 정렬 여부는 _build_columns가 이미 처리했으므로 여기서는 다시 안 본다.
    """
    sorted_idx = sorted(col_indices, key=lambda i: lines[i].bbox[1])

    candidates = []  # (num, y_top, y_bottom_hint)
    for i in sorted_idx:
        l = lines[i]
        m = ANCHOR.match(l.text)
        if m:
            candidates.append((int(m.group(1)), l.bbox[1], l.bbox[3]))

    # LIS: num 기준 최장 증가 부분수열 (읽는 순서 = y 오름차순 유지)
    lis = _longest_increasing(candidates, key=lambda c: c[0])
    anchors = [_Anchor(num=n, top=top, bottom_hint=bot) for n, top, bot in lis]

    # 결번 복구: 연속된 두 앵커 사이 번호가 1개 이상 비면 시도한다.
    recovered: list[_Anchor] = []
    for a, b in zip(anchors, anchors[1:]):
        missing = list(range(a.num + 1, b.num))
        if not missing:
            continue
        span_top, span_bottom = a.top, b.top
        for k, num in enumerate(missing):
            # 1) 범위 지시문이 이 번호로 시작하면 그 줄의 y를 앵커 시작으로 채택
            header_hit = next((h for h in headers if h[0] == num and span_top <= h[3].bbox[1] < span_bottom), None)
            if header_hit is not None:
                top = header_hit[3].bbox[1]
            else:
                # 2) 힌트가 없으면 구간을 결번 개수+1 등분해 선형 보간
                step = (span_bottom - span_top) / (len(missing) + 1)
                top = span_top + step * (k + 1)
            recovered.append(_Anchor(num=num, top=int(top), bottom_hint=int(top), recovered=True))

    anchors.extend(recovered)
    anchors.sort(key=lambda a: a.top)
    return anchors


def _longest_increasing(items, key):
    """items(이미 읽는 순서로 정렬됨)에서 key 기준 최장 증가 부분수열을 반환."""
    if not items:
        return []
    piles: list[int] = []  # 각 파일의 마지막 값
    pile_items: list[list] = []
    prev = [-1] * len(items)
    tails_idx: list[int] = []

    seq = [key(it) for it in items]
    tails_vals: list[int] = []
    tails_pos: list[int] = []
    for i, v in enumerate(seq):
        pos = bisect.bisect_left(tails_vals, v)
        if pos == len(tails_vals):
            tails_vals.append(v)
            tails_pos.append(i)
        else:
            tails_vals[pos] = v
            tails_pos[pos] = i
        prev[i] = tails_pos[pos - 1] if pos > 0 else -1
    # 재구성
    if not tails_pos:
        return []
    result_idx = []
    i = tails_pos[-1]
    while i != -1:
        result_idx.append(i)
        i = prev[i]
    result_idx.reverse()
    return [items[i] for i in result_idx]


def locate_question(lines: list[Line], finger: tuple[int, int], page_h: int) -> LocateResult:
    fx, fy = finger

    # 0. 헤더/푸터 제외
    body_lines = [l for l in lines if page_h * 0.05 < l.bbox[1] < page_h * 0.95]
    if not body_lines:
        raise LocateError("본문 라인이 없음 (헤더/푸터 필터 후 전부 제거됨)")

    # 페이지 폭 파라미터가 없으므로, 본문 라인들의 최대 우측 경계를 근사치로 쓴다.
    page_w = max(l.bbox[2] for l in body_lines)

    headers = _find_range_header(body_lines)
    line_heights = [l.bbox[3] - l.bbox[1] for l in body_lines]
    median_h = median(line_heights)

    columns = _build_columns(body_lines, gap=page_w * 0.15)
    if not columns:
        raise LocateError("페이지 전체에서 번호 앵커를 하나도 찾지 못함")

    # 컬럼별 앵커 확정 (결번 복구 포함)
    col_anchors = []
    for col_left, col in columns:
        anchors = _build_anchors_for_column(col, body_lines, headers)
        col_anchors.append((col, anchors, col_left))

    # 5. 손끝 → 최근접 "줄"
    target_i = min(range(len(body_lines)), key=lambda i: _rect_dist(body_lines[i].bbox, fx, fy))
    target = body_lines[target_i]
    dist = _rect_dist(target.bbox, fx, fy)
    locate_confidence = "low" if dist > median_h * 1.5 else "high"

    # target이 속한 컬럼 찾기
    target_col = None
    for col, anchors, col_left in col_anchors:
        if target_i in col:
            target_col = (col, anchors, col_left)
            break
    if target_col is None:
        raise LocateError("손끝에 가장 가까운 줄이 속한 컬럼을 찾지 못함")

    col, anchors, col_left = target_col

    if not anchors:
        raise LocateError("이 컬럼에서 번호 앵커를 하나도 찾지 못함 (폴백 사다리 미구현 구간)")

    # target보다 위(또는 같은 y)에 있는 마지막 앵커 = target이 속한 밴드의 시작 앵커
    anchors_sorted = sorted(anchors, key=lambda a: a.top)
    band_anchor = None
    next_top = None
    for idx, a in enumerate(anchors_sorted):
        if a.top <= target.bbox[1]:
            band_anchor = a
            next_top = anchors_sorted[idx + 1].top if idx + 1 < len(anchors_sorted) else None
        else:
            break

    if band_anchor is None:
        # 손끝이 첫 앵커보다도 위에 있는 경우: 첫 앵커로 폴백
        band_anchor = anchors_sorted[0]
        next_top = anchors_sorted[1].top if len(anchors_sorted) > 1 else None

    band_top = band_anchor.top
    band_bottom = next_top if next_top is not None else max(l.bbox[3] for i, l in enumerate(body_lines) if i in col)

    band_lines = [l for i, l in enumerate(body_lines) if i in col and band_top <= l.bbox[1] < band_bottom]

    num = band_anchor.num
    anchor_recovered = band_anchor.recovered

    # 6. 범위 지시문 병합 (밴드 내부 여부와 무관하게 span으로 조회)
    range_header_text = None
    range_span = None
    header_line = None
    for start, end, body, hline in headers:
        if start <= num <= end:
            range_header_text = body
            range_span = (start, end)
            header_line = hline
            break

    stripped_bodies = [_strip_anchor(l.text) for l in band_lines]
    stripped_bodies = [b for b in stripped_bodies if b]
    query_parts = ([range_header_text] if range_header_text else []) + stripped_bodies
    query_text = " ".join(p for p in query_parts if p)

    box_sources = ([header_line.bbox] if header_line else []) + [l.bbox for l in band_lines]
    x1 = min(b[0] for b in box_sources)
    y1 = min(b[1] for b in box_sources)
    x2 = max(b[2] for b in box_sources)
    y2 = max(b[3] for b in box_sources)

    # LIS 통과 후 이 컬럼에 남은(복구분 제외) 실제 검출 앵커 수로 fallback_level 판단
    detected_count = sum(1 for a in anchors if not a.recovered)
    if detected_count >= 2:
        fallback_level = 1
    elif detected_count == 1:
        fallback_level = 2
    else:
        fallback_level = 3

    return LocateResult(
        question_number=num,
        query_text=query_text,
        box=(x1, y1, x2, y2),
        range_header=range_header_text,
        range_span=range_span,
        anchor_recovered=anchor_recovered,
        locate_confidence=locate_confidence,
        fallback_level=fallback_level,
    )
