"""
gemini_config.generate_json의 JSON 파싱 실패 재시도 테스트 (2026-10-26).
Gemini가 JSON 모드에서도 쉼표가 빠진 JSON을 보낸 실측 사례(속도측정 hand_one4)가 있어서,
파싱에 실패하면 한 번 더 부르도록 했다. 실제 Gemini는 부르지 않는다.
"""
import json
from types import SimpleNamespace

import pytest

from gemini_config import generate_json


def _fake_model(texts):
    it = iter(texts)
    return SimpleNamespace(generate_content=lambda parts: SimpleNamespace(text=next(it)))


def test_retries_once_when_json_is_broken():
    broken = '{"answer": "1번" "explanation_text": "해설"}'  # 쉼표 누락
    ok = json.dumps({"answer": "1번", "explanation_text": "해설"})
    parsed, info = generate_json(_fake_model([broken, ok]), ["prompt"])
    assert parsed["answer"] == "1번"
    assert info["json_retries"] == 1


def test_no_retry_when_first_response_is_valid():
    parsed, info = generate_json(_fake_model(['{"answer": "2번"}']), ["prompt"])
    assert parsed == {"answer": "2번"}
    assert info["json_retries"] == 0


def test_raises_after_retries_exhausted():
    broken = '{"answer": "1번" "x": 1}'
    with pytest.raises(json.JSONDecodeError):
        generate_json(_fake_model([broken, broken]), ["prompt"])
