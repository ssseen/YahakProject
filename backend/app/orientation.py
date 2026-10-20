"""
페이지 방향 판정 + 좌표/이미지 회전 — 종이를 옆으로(또는 거꾸로) 놓고 찍은 사진을
Clova 재호출 없이 똑바로 세운다.

배경(2026-09-30): 100장 실측에서 16장이 "휴대폰은 세로로 들었는데 종이가 책상에 옆으로
놓인" 사진이었다. EXIF 회전값은 정상(1)이라 exif_transpose로는 못 고치는 경우다. 그래도
Clova는 누운 글자를 문장 그대로 정확히 읽고, 좌표 축만 누워 있다(줄 bbox가 세로로 긺).
그러면 question_locator의 컬럼(x)/읽는 순서(y) 판정이 전부 뒤바뀐다.

방법: Clova가 주는 단어(field) 좌표를 한 줄 안에서 순서대로 보면, 다음 단어로 넘어갈 때
중심점이 이동하는 방향이 곧 "글 읽는 방향"이다. 단어 수백 개가 투표하므로 안정적이다.
  오른쪽 → 0°(정상) / 아래쪽 → 90°(시계방향으로 누움, 페이지 위쪽이 사진 오른쪽)
  위쪽   → 270°(반시계방향으로 누움) / 왼쪽 → 180°(거꾸로)
판정된 각도만큼 줄 bbox·손끝·이미지를 반대로 돌리면 똑바로 선 페이지 좌표계가 된다.

이 파일은 순수 좌표 산술이며(이미지 회전만 cv2.rotate 사용) 네트워크 호출이 없다.
"""
import copy

import cv2

from app.question_locator import Line

# 투표 결과를 믿을 최소 조건. 단어 전환이 너무 적거나(글자가 거의 없는 사진) 1등 방향의
# 득표율이 낮으면(방향이 뒤섞인 페이지) 돌리지 않고 0°로 둔다 - 잘못 돌리면 멀쩡한 사진을
# 망가뜨리므로 애매하면 아무것도 안 하는 쪽이 안전하다.
_MIN_VOTES = 20
_MIN_SHARE = 0.6

_CV2_ROTATE = {
    # 판정 각도 -> 똑바로 세우기 위한 이미지 회전 (판정 방향의 반대로 돌림)
    90: cv2.ROTATE_90_COUNTERCLOCKWISE,
    180: cv2.ROTATE_180,
    270: cv2.ROTATE_90_CLOCKWISE,
}


def _center(field):
    verts = field["boundingPoly"]["vertices"]
    return (sum(v["x"] for v in verts) / len(verts), sum(v["y"] for v in verts) / len(verts))


def detect_rotation(clova_response: dict) -> tuple[int, dict]:
    """Clova 원본 응답의 단어 좌표로 페이지가 몇 도 누웠는지 판정한다.
    반환: (0|90|180|270, 방향별 득표수 dict) - 득표수는 로그/디버깅용."""
    images = clova_response.get("images") or []
    fields = (images[0].get("fields") or []) if images else []

    votes = {0: 0, 90: 0, 180: 0, 270: 0}
    prev = None
    for f in fields:
        c = _center(f)
        if prev is not None:
            dx, dy = c[0] - prev[0], c[1] - prev[1]
            if abs(dx) > abs(dy):
                votes[0 if dx > 0 else 180] += 1
            elif dy != 0:
                votes[90 if dy > 0 else 270] += 1
        # 줄이 바뀌는 지점(lineBreak)의 이동은 "다음 줄 첫 단어로 되돌아가는" 움직임이라
        # 읽는 방향과 무관하므로 세지 않는다.
        prev = None if f.get("lineBreak") else c

    total = sum(votes.values())
    best = max(votes, key=votes.get)
    if total < _MIN_VOTES or votes[best] / total < _MIN_SHARE:
        return 0, votes
    return best, votes


def upright_size(angle: int, w: int, h: int) -> tuple[int, int]:
    return (h, w) if angle in (90, 270) else (w, h)


def rotate_point(x: float, y: float, angle: int, w: int, h: int) -> tuple[float, float]:
    """누운 사진(w x h) 좌표 -> 똑바로 세운 좌표. _CV2_ROTATE의 이미지 회전과 픽셀 단위로 일치."""
    if angle == 90:
        return y, w - 1 - x
    if angle == 270:
        return h - 1 - y, x
    if angle == 180:
        return w - 1 - x, h - 1 - y
    return x, y


def rotate_bbox(bbox, angle: int, w: int, h: int) -> tuple[int, int, int, int]:
    ax, ay = rotate_point(bbox[0], bbox[1], angle, w, h)
    bx, by = rotate_point(bbox[2], bbox[3], angle, w, h)
    return (int(min(ax, bx)), int(min(ay, by)), int(max(ax, bx)), int(max(ay, by)))


def rotate_lines(lines: list[Line], angle: int, w: int, h: int) -> list[Line]:
    if angle == 0:
        return lines
    return [Line(l.text, rotate_bbox(l.bbox, angle, w, h)) for l in lines]


def rotate_response(response: dict, angle: int, w: int, h: int) -> dict:
    """Clova 응답의 모든 단어 꼭짓점을 똑바로 세운 좌표로 옮긴 복사본 (to_lines에 그대로 넣을 수 있음).
    줄 박스가 아니라 단어 단위로 돌려야, 뒤이은 기울기 보정(app/deskew.py)도 단어 단위로 이어서 할 수 있다."""
    if angle == 0:
        return response
    out = copy.deepcopy(response)
    im = out["images"][0]
    for f in im.get("fields") or []:
        for v in f["boundingPoly"]["vertices"]:
            v["x"], v["y"] = rotate_point(v["x"], v["y"], angle, w, h)
    nw, nh = upright_size(angle, w, h)
    im["convertedImageInfo"] = {**(im.get("convertedImageInfo") or {}), "width": nw, "height": nh}
    return out


def rotate_image(img, angle: int):
    """cv2 이미지를 똑바로 세운다 (angle=0이면 그대로 반환)."""
    if angle == 0:
        return img
    return cv2.rotate(img, _CV2_ROTATE[angle])
