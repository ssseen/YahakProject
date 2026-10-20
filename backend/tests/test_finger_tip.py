"""
vision_processor 손끝 검출 보조 함수 테스트 (네트워크 호출 없음).
"""
import numpy as np

from vision_processor import _merge_ring_split, _RING_GAP_PX


def _rect(x1, y1, x2, y2):
    """사각형 외곽선 (cv2.findContours 형식: N x 1 x 2)."""
    return np.array([[[x1, y1]], [[x2, y1]], [[x2, y2]], [[x1, y2]]], dtype=np.int32)


SHAPE = (1000, 1000)  # (h, w)


def test_ring_split_fingertip_is_merged_with_hand():
    # 반지 사례: 손 조각은 사진 왼쪽 가장자리에서 들어오고, 손가락 끝 조각은 반지 너머에 떠 있음
    hand = _rect(0, 400, 300, 500)
    tip = _rect(300 + _RING_GAP_PX // 2, 420, 500, 480)
    merged = _merge_ring_split(hand, [hand, tip], SHAPE)
    assert len(merged.reshape(-1, 2)) == 8


def test_isolated_tip_chosen_also_merges_hand():
    hand = _rect(0, 400, 300, 500)
    tip = _rect(300 + _RING_GAP_PX // 2, 420, 500, 480)
    merged = _merge_ring_split(tip, [hand, tip], SHAPE)
    assert len(merged.reshape(-1, 2)) == 8


def test_two_border_touching_pieces_are_not_merged():
    # 다른 손가락·종이 가장자리 띠처럼 둘 다 사진 가장자리에서 들어오면 합치지 않음 (299, 308.jpg)
    finger = _rect(600, 300, 999, 380)
    other = _rect(600, 420, 999, 470)
    assert _merge_ring_split(finger, [finger, other], SHAPE) is finger


def test_far_piece_is_not_merged():
    hand = _rect(0, 400, 300, 500)
    far = _rect(300 + _RING_GAP_PX * 3, 420, 800, 480)
    assert _merge_ring_split(hand, [hand, far], SHAPE) is hand
