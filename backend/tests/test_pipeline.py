"""
pipeline.py의 순수 로직 함수 테스트 (네트워크 호출 없음).
"""
from types import SimpleNamespace

from app.question_locator import Line
from pipeline import (
    _format_similar_questions,
    _fraction_tall_lines,
    _ROTATION_SANITY_THRESHOLD,
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


# 회귀 방지: 35.jpg 실사례(2026-09-14) - Clova가 페이지 방향은 정상 업로드(EXIF
# 정상, 육안 확인 완료) 받고도 텍스트를 세로로 오인식해 모든 줄의 bbox가
# 높이>>너비로 나온 적이 있음. _fraction_tall_lines가 이걸 감지해야 회전 재시도가
# 트리거된다.
def test_fraction_tall_lines_all_normal_horizontal():
    lines = [Line("normal text", (0, 0, 300, 40)), Line("another line", (0, 50, 280, 90))]
    assert _fraction_tall_lines(lines) == 0.0


def test_fraction_tall_lines_all_misread_as_vertical():
    # 35.jpg 실측과 같은 패턴: 폭은 좁고(40px대) 높이가 수백~천대인 줄들
    lines = [Line("which", (101, 168, 144, 283)), Line("A: ...", (45, 529, 97, 1389))]
    assert _fraction_tall_lines(lines) == 1.0
    assert _fraction_tall_lines(lines) > _ROTATION_SANITY_THRESHOLD


def test_fraction_tall_lines_empty_list():
    assert _fraction_tall_lines([]) == 0.0


# 회귀 방지: 103.jpg 실사례(2026-09-15) - _retake_response에 "message" 필드가 없어서
# 프론트(photo-processing.js)가 errorMessage = data.message를 그대로 화면에 찍을 때
# 문자 그대로 "undefined"가 떴다. 모든 reason에 대해 message가 항상 채워져야 한다.
def test_retake_response_always_has_nonempty_message():
    for reason in ["no_finger", "no_text", "location_failed", "rotation_misdetected", "unknown_future_reason"]:
        r = _retake_response(reason=reason)
        assert r["status"] == "retake"
        assert isinstance(r.get("message"), str) and r["message"].strip() != ""
