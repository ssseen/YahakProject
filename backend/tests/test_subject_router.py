from dataclasses import dataclass, field

from app.subject_router import decide_branch, select_similar


@dataclass
class FakeMatch:
    id: str
    score: float
    fields: dict = field(default_factory=dict)


def _matches(subject, score, count, id_prefix="m"):
    return [FakeMatch(id=f"{id_prefix}{i}", score=score, fields={"subject": subject})
            for i in range(count)]


def test_english_text_all_english_neighbors_branches_english():
    query_text = "The mouse is tiny and the elephant is huge."
    matches = _matches("영어", 0.5, 5)
    result = decide_branch(matches, query_text)
    assert result.branch == "영어"


def test_korean_mixed_guksagwa_subjects_branches_guksagwa():
    query_text = "다음 그림을 보고 물음에 답하시오. 우리나라의 계절 변화는 지구의 자전축 기울기와 관련이 있다."
    matches = (
        _matches("국어", 0.5, 2, "kr")
        + _matches("사회", 0.5, 2, "sc")
        + _matches("과학", 0.5, 2, "sci")
    )
    result = decide_branch(matches, query_text)
    assert result.branch == "국사과"


def test_latin_ratio_guard_overrides_to_english():
    # 라틴 비율 0.8 (라틴 8자 / 총 10자), 이웃은 전부 "국어" -> 그대로면 국사과가
    # 되지만 라틴 가드가 영어로 강제한다.
    query_text = "abcdefgh가나"
    assert abs(0.8 - (8 / 10)) < 1e-9
    matches = _matches("국어", 0.5, 5)
    result = decide_branch(matches, query_text)
    assert result.branch == "영어"
    assert result.guard == "latin_override"


def test_short_text_with_math_symbols_falls_back_to_math():
    # 20자 미만 + 수식 기호(=, /, ^) 4개 이상, 라틴 문자는 전혀 없음(가드1 회피).
    query_text = "3/4=0.75이고 2^3=8이다"
    assert len(query_text.strip()) < 30
    result = decide_branch([], query_text)
    assert result.branch == "수학"
    assert result.guard == "math_fallback"


def test_select_similar_returns_low_score_second_place():
    # 점수 하한선이 없으므로, 2위 점수가 낮아도(0.05) 그대로 반환돼야 한다.
    matches = _matches("영어", 0.9, 1) + _matches("영어", 0.05, 1, "low")
    result = select_similar(matches, "영어", exclude_id=None)
    assert [m.id for m in result] == ["low0"]


def test_select_similar_skips_top_rank():
    # 1위(가장 높은 점수)는 사진 찍은 문제 자체(또는 재수록본)일 가능성이 높아서
    # "유사문제 풀어보기"에는 부적절 - 2위부터 최대 3건을 반환해야 한다.
    matches = _matches("영어", 0.9, 5)  # 입력 순서 = 점수 순위(m0이 1위)
    result = select_similar(matches, "영어", exclude_id=None)
    assert [m.id for m in result] == ["m1", "m2", "m3"]


def test_select_similar_only_top_rank_eligible_returns_empty():
    matches = _matches("영어", 0.9, 1)  # 1위 하나뿐, 2위가 없음
    result = select_similar(matches, "영어", exclude_id=None)
    assert result == []
