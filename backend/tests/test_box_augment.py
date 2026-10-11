"""
vision_processor.augment_box_with_ink 테스트 (네트워크 호출 없음, 합성 이미지만 사용).
"""
import cv2
import numpy as np

from vision_processor import augment_box_with_ink

PAGE = (400, 400)  # (h, w)


def _white_page():
    return np.full((*PAGE, 3), 255, dtype=np.uint8)


def test_nearby_picture_is_included():
    img = _white_page()
    text_box = (50, 50, 150, 80)
    # 텍스트 박스 바로 아래, 글자 없는 검은 사각형(그림 대용) - gap < 90px
    cv2.rectangle(img, (50, 100), (150, 160), (0, 0, 0), -1)

    box = augment_box_with_ink(img, text_box, col_x_range=(0, 400), band_y_range=(0, 400))

    assert box[1] <= 50
    assert box[3] >= 160  # 아래쪽 그림까지 포함됨


def test_distant_content_is_not_included():
    img = _white_page()
    text_box = (50, 50, 150, 80)
    # col_x_range/band_y_range 안이지만 text_box에서 아주 멀리(200px+) 떨어진 잉크
    cv2.rectangle(img, (50, 300), (150, 360), (0, 0, 0), -1)

    box = augment_box_with_ink(img, text_box, col_x_range=(0, 400), band_y_range=(0, 400))

    assert box == text_box  # 멀리 떨어진 블록은 안 붙음


def test_skin_colored_region_is_excluded():
    img = _white_page()
    text_box = (50, 50, 150, 80)
    # 텍스트 박스 바로 옆, 피부색 영역(손가락 대용) - BGR as HSV(10,100,180)
    skin_bgr = tuple(int(c) for c in cv2.cvtColor(
        np.uint8([[[10, 100, 180]]]), cv2.COLOR_HSV2BGR)[0, 0])
    cv2.rectangle(img, (150, 50), (200, 80), skin_bgr, -1)

    box = augment_box_with_ink(img, text_box, col_x_range=(0, 400), band_y_range=(0, 400))

    assert box[2] < 200  # 손가락 쪽으로 안 번짐


def test_search_window_clipped_to_image_bounds():
    img = _white_page()
    text_box = (10, 10, 50, 30)
    # 범위가 이미지 밖까지 나가도 에러 없이 동작해야 함
    box = augment_box_with_ink(img, text_box, col_x_range=(-100, 1000), band_y_range=(-100, 1000))
    assert box[0] <= text_box[0] and box[2] >= text_box[2]


def test_degenerate_range_returns_text_box_unchanged():
    img = _white_page()
    text_box = (50, 50, 150, 80)
    # y 범위가 뒤집혀 있으면(비정상 입력) 원래 박스를 그대로 반환
    box = augment_box_with_ink(img, text_box, col_x_range=(0, 400), band_y_range=(300, 100))
    assert box == text_box
