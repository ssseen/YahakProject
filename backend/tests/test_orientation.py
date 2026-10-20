"""
app/orientation.py 테스트 (네트워크 호출 없음) - 글 읽는 방향 판정과 좌표/이미지 회전.
"""
import numpy as np

from app.orientation import detect_rotation, rotate_point, rotate_image, upright_size


def _response(words_per_line, n_lines, step, line_step):
    """단어를 step 방향으로 이어 붙인 줄을 line_step 방향으로 쌓은 가짜 Clova 응답."""
    fields = []
    for li in range(n_lines):
        for wi in range(words_per_line):
            cx = 500 + step[0] * wi + line_step[0] * li
            cy = 500 + step[1] * wi + line_step[1] * li
            fields.append({
                "inferText": "w",
                "boundingPoly": {"vertices": [{"x": cx - 5, "y": cy - 5}, {"x": cx + 5, "y": cy - 5},
                                              {"x": cx + 5, "y": cy + 5}, {"x": cx - 5, "y": cy + 5}]},
                "lineBreak": wi == words_per_line - 1,
            })
    return {"images": [{"fields": fields}]}


def test_upright_page_is_zero():
    assert detect_rotation(_response(6, 10, (40, 0), (0, 30)))[0] == 0


def test_text_flowing_down_is_90():
    # 70.jpg 실측 패턴: 줄 안에서 단어가 아래로 이어지고, 다음 줄은 왼쪽에 있음
    assert detect_rotation(_response(6, 10, (0, 40), (-30, 0)))[0] == 90


def test_text_flowing_up_is_270():
    assert detect_rotation(_response(6, 10, (0, -40), (30, 0)))[0] == 270


def test_upside_down_is_180():
    assert detect_rotation(_response(6, 10, (-40, 0), (0, -30)))[0] == 180


def test_line_break_jump_is_not_counted():
    # 줄이 바뀔 때 "다음 줄 첫 단어로 되돌아가는" 큰 이동은 투표에서 빠져야 한다 -
    # 줄당 단어가 2개뿐이라 되돌아가는 이동을 셌다면 0°와 180°가 비슷하게 나왔을 것.
    angle, votes = detect_rotation(_response(2, 30, (40, 0), (0, 30)))
    assert angle == 0 and votes[180] == 0


def test_too_few_words_stays_zero():
    # 글자가 거의 없으면(투표 부족) 잘못 돌리지 않도록 0°로 둔다
    assert detect_rotation(_response(3, 2, (0, 40), (-30, 0)))[0] == 0


def test_empty_response():
    assert detect_rotation({"images": []})[0] == 0
    assert detect_rotation({})[0] == 0


def test_rotate_point_matches_image_rotation():
    # 좌표 변환이 cv2 이미지 회전과 픽셀 단위로 일치해야 빨간 박스가 제자리에 그려진다
    h, w = 7, 11
    for angle in (0, 90, 180, 270):
        img = np.zeros((h, w), np.uint8)
        img[2, 3] = 255  # (x=3, y=2)
        out = rotate_image(img, angle)
        assert (out.shape[1], out.shape[0]) == upright_size(angle, w, h)
        ys, xs = np.nonzero(out)
        assert (xs[0], ys[0]) == rotate_point(3, 2, angle, w, h)
