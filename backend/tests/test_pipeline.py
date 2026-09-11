"""
pipeline.py의 순수 로직 함수 테스트 (네트워크 호출 없음).
"""
from types import SimpleNamespace

from pipeline import _format_similar_questions


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
