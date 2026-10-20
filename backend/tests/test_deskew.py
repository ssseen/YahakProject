"""
app/deskew.py 테스트 (네트워크 호출 없음) - 기울기 측정과 사진·좌표 펴기.
"""
import numpy as np

from app.deskew import estimate_skew_ocr, deskew_matrix, warp_response, warp_point, warp_image


def _tilted_response(angle_deg, n_lines=8, words=6):
    """angle_deg만큼 기운(오른쪽으로 갈수록 내려가는 것이 양수) 가짜 Clova 응답."""
    t = np.tan(np.radians(angle_deg))
    fields = []
    for li in range(n_lines):
        for wi in range(words):
            cx, cy = 100 + 60 * wi, 200 + 50 * li + 60 * wi * t
            fields.append({
                "inferText": "w",
                "boundingPoly": {"vertices": [{"x": cx - 20, "y": cy - 10}, {"x": cx + 20, "y": cy - 10},
                                              {"x": cx + 20, "y": cy + 10}, {"x": cx - 20, "y": cy + 10}]},
                "lineBreak": wi == words - 1,
            })
    return {"images": [{"fields": fields, "convertedImageInfo": {"width": 600, "height": 800}}]}


def test_estimate_skew_ocr_measures_angle():
    for a in (-10, -3, 0, 5, 12):
        assert abs(estimate_skew_ocr(_tilted_response(a)) - a) < 0.5


def test_too_few_lines_returns_none():
    assert estimate_skew_ocr(_tilted_response(5, n_lines=2)) is None
    assert estimate_skew_ocr({"images": []}) is None


def test_warp_response_flattens_lines():
    # 편 뒤 다시 재면 기울기가 거의 0이어야 한다 (부호가 틀리면 두 배로 기울어짐)
    resp = _tilted_response(8)
    M, nw, nh = deskew_matrix(8, 600, 800)
    flat = warp_response(resp, M, nw, nh)
    assert abs(estimate_skew_ocr(flat)) < 0.5
    assert flat["images"][0]["convertedImageInfo"]["width"] == nw


def test_warp_point_matches_image_warp():
    # 손끝 좌표 변환이 사진 변환과 같은 위치를 가리켜야 빨간 박스·손끝이 제자리에 그려진다
    # 펼 때 생기는 빈 모서리는 흰색으로 채워지므로, 흰 바탕에 검은 점으로 확인한다
    img = np.full((80, 120, 3), 255, np.uint8)
    img[30, 50] = 0
    M, nw, nh = deskew_matrix(10, 120, 80)
    out = warp_image(img, M, nw, nh)
    ys, xs = np.nonzero(out[:, :, 0] < 200)
    x, y = warp_point(50, 30, M)
    assert abs(xs.mean() - x) < 1.5 and abs(ys.mean() - y) < 1.5
