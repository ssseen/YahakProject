"""음성 인식 힌트(문항 글자 -> Whisper 프롬프트) 테스트"""
import threading
import time
from types import SimpleNamespace

import pipeline
from pipeline import make_stt_hint, session_hint


def test_hint_keeps_words_in_order_without_numbers_and_duplicates():
    text = "3. 다음 중 빗살무늬 토기를 처음 사용한 시대는? ① 구석기 ② 신석기 ③ 청동기 ④ 철기 빗살무늬"
    assert make_stt_hint(text) == "다음 빗살무늬 토기를 처음 사용한 시대는 구석기 신석기 청동기 철기"


def test_hint_is_capped_on_word_boundary():
    words = [chr(0xAC00 + i) + "낱말" for i in range(200)]  # 서로 다른 낱말 200개
    hint = make_stt_hint(" ".join(words))
    assert len(hint) <= pipeline._HINT_MAX_CHARS
    assert hint.split(" ") == words[:len(hint.split(" "))]  # 낱말 중간에서 잘리지 않음


def test_hint_empty_text():
    assert make_stt_hint("") == ""
    assert make_stt_hint(None) == ""


def _put_session(sid, done, fail=None, query_text="빗살무늬 토기"):
    entry = {"created": time.time(), "done": threading.Event(), "fail": fail,
             "ctx": {"locate_result": SimpleNamespace(query_text=query_text)}, "timings": {}}
    if done:
        entry["done"].set()
    pipeline._SESSIONS[sid] = entry
    return entry


def test_session_hint_states():
    try:
        assert session_hint("nope") is None
        _put_session("wait", done=False)
        assert session_hint("wait") == {"ready": False, "hint": None}
        _put_session("ok", done=True)
        assert session_hint("ok") == {"ready": True, "hint": "빗살무늬 토기"}
        _put_session("fail", done=True, fail={"status": "retake"})
        assert session_hint("fail") == {"ready": True, "hint": None}
        # 들여다보기만 하고 세션은 그대로 남아 있어야 해설 요청이 쓸 수 있다
        assert "ok" in pipeline._SESSIONS
    finally:
        for k in ("wait", "ok", "fail"):
            pipeline._SESSIONS.pop(k, None)
