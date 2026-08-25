import glob
import json
import os

import pytest

from app.clova_client import to_lines

_OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "out")


def _load_fixture():
    """
    out/clova_raw_*.json 중 실제 Clova 실호출 결과(scripts/clova_probe.py로 생성됨)를
    픽스처로 쓴다. 여러 개 있으면 필드가 가장 많은(=페이지 전체 사진) 것을 고른다.
    네트워크 호출은 하지 않는다.
    """
    paths = glob.glob(os.path.join(_OUT_DIR, "clova_raw_*.json"))
    if not paths:
        pytest.skip("out/clova_raw_*.json이 없음 - 먼저 scripts/clova_probe.py를 실행해야 함")
    best_path, best_data, best_count = None, None, -1
    for p in paths:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        count = len(data.get("images", [{}])[0].get("fields", []))
        if count > best_count:
            best_path, best_data, best_count = p, data, count
    return best_path, best_data


def test_to_lines_line_count_nonzero():
    _, data = _load_fixture()
    result = to_lines(data)
    assert len(result["lines"]) > 0


def test_to_lines_all_bboxes_valid():
    _, data = _load_fixture()
    result = to_lines(data)
    for line in result["lines"]:
        x1, y1, x2, y2 = line.bbox
        assert x1 < x2
        assert y1 < y2


def test_to_lines_page_conf_min_in_range():
    _, data = _load_fixture()
    result = to_lines(data)
    assert result["page_conf_min"] is not None
    assert 0.0 <= result["page_conf_min"] <= 1.0


def test_to_lines_low_conf_line_indices_are_valid():
    _, data = _load_fixture()
    result = to_lines(data)
    n = len(result["lines"])
    for idx in result["low_conf_lines"]:
        assert 0 <= idx < n


if __name__ == "__main__":
    path, data = _load_fixture()
    result = to_lines(data)
    print(f"픽스처: {path}")
    print(f"page_w={result['page_w']} page_h={result['page_h']} "
          f"page_conf_min={result['page_conf_min']:.4f} "
          f"low_conf_lines={result['low_conf_lines']}")
    print(f"총 {len(result['lines'])}줄, 앞 15개:")
    for i, line in enumerate(result["lines"][:15]):
        print(f"{i:2d}: {line.text!r}  bbox={line.bbox}")
