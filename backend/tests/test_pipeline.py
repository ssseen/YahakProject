"""
pipeline.py의 순수 로직 함수 테스트 (네트워크 호출 없음).
"""
from types import SimpleNamespace

from pipeline import (
    _format_similar_questions,
    _retake_response,
)


def _match(id_="q1", score=0.64, **fields):
    return SimpleNamespace(id=id_, score=score, fields=fields)


def test_format_similar_questions_has_image_true():
    matches = [_match(has_image="1", image_path="https://example.com/a.png")]
    out = _format_similar_questions(matches)
    assert out[0]["has_image"] is True
    assert out[0]["image_path"] == "https://example.com/a.png"


def test_format_similar_questions_has_image_false():
    matches = [_match(has_image="0", image_path="")]
    out = _format_similar_questions(matches)
    assert out[0]["has_image"] is False
    assert out[0]["image_path"] == ""


def test_format_similar_questions_has_image_missing_defaults_false():
    # has_image/image_path 필드 자체가 없는 옛 인덱스 데이터와도 안 깨지는지 확인
    matches = [_match()]
    out = _format_similar_questions(matches)
    assert out[0]["has_image"] is False
    assert out[0]["image_path"] == ""


def test_format_similar_questions_question_choices_split():
    matches = [_match(text="지문+보기 뭉친것", question="지문만", choices="보기만")]
    out = _format_similar_questions(matches)
    assert out[0]["text"] == "지문+보기 뭉친것"
    assert out[0]["question"] == "지문만"
    assert out[0]["choices"] == "보기만"


def test_format_similar_questions_passthrough_fields():
    matches = [_match(answer="3", explanation="해설", year="2022",
                      exam_round="2", question_number="3")]
    out = _format_similar_questions(matches)
    row = out[0]
    assert row["id"] == "q1"
    assert row["score"] == 0.64
    assert row["answer"] == "3"
    assert row["explanation"] == "해설"
    assert row["year"] == "2022"
    assert row["exam_round"] == "2"
    assert row["question_number"] == "3"


# 회귀 방지: 103.jpg 실사례(2026-09-15) - _retake_response에 "message" 필드가 없어서
# 프론트(photo-processing.js)가 errorMessage = data.message를 그대로 화면에 찍을 때
# 문자 그대로 "undefined"가 떴다. 모든 reason에 대해 message가 항상 채워져야 한다.
def test_retake_response_always_has_nonempty_message():
    for reason in ["no_finger", "no_text", "location_failed", "rotation_misdetected", "unknown_future_reason"]:
        r = _retake_response(reason=reason)
        assert r["status"] == "retake"
        assert isinstance(r.get("message"), str) and r["message"].strip() != ""
