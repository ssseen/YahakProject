from app.question_locator import Line, locate_question

LINES = [
    Line("2026년도 제1회 중학교 졸업학력 검정고시", (441, 59, 1029, 83)),
    Line("제 3 교시  영 어", (343, 108, 784, 147)),
    Line("1. 다음 중 밑줄 친 단어의 뜻으로 가장 적절한 것은?", (100, 304, 681, 326)),
    Line("Modern cameras are very simple to use.", (123, 343, 613, 365)),
    Line("① 단순한 ② 무거운 ③ 신기한 ④ 어려운", (105, 392, 637, 414)),
    Line("2. 다음 중 밑줄 친 두 단어의 의미 관계와 다른 것은?", (100, 578, 681, 600)),
    Line("The mouse is tiny and the elephant is huge.", (123, 613, 652, 634)),
    Line("① cheap － expensive  ② far － long", (105, 657, 637, 677)),
    Line("③ low － high  ④ thin － thick", (105, 684, 637, 704)),
    Line("[3～4] 다음 중 빈칸에 들어갈 말로 가장 적절한 것을 고르시오.", (100, 735, 683, 757)),
    Line("3.", (100, 769, 123, 789)),
    Line("James is good at soccer, but he ____ good at baseball.", (123, 804, 657, 826)),
    Line("① are  ② aren't  ③ do  ④ isn't", (105, 848, 632, 868)),
    Line("4.", (100, 897, 123, 916)),
    Line("You should leave now, ____ you'll miss the train.", (123, 931, 647, 953)),
    Line("① in  ② or  ③ to  ④ with", (105, 975, 632, 996)),
    Line("[5～6] 다음 중 대화의 빈칸에 들어갈 말로 가장 적절한 것을 고르시오.", (100, 1024, 683, 1068)),
    Line("5.", (100, 1083, 123, 1103)),
    Line("A: ____ should I do to stay healthy?", (123, 1117, 637, 1139)),
    Line("9. 그림으로 보아 다음 빈칸에 들어갈 말로 가장 적절한 것은?", (786, 304, 1367, 326)),
    Line("A: What is the boy doing?", (833, 353, 1176, 375)),
    Line("① baking cookies ② throwing a ball", (791, 421, 1323, 442)),
    Line("10. 다음 대화가 끝난 후 두 사람이 함께 할 일은?", (786, 490, 1323, 512)),
    Line("A: I heard the new singer has a concert this Saturday.", (833, 529, 1352, 551)),
    Line("중졸 (영어) 2－1", (637, 1901, 833, 1926)),
]

PAGE_H = 1960


def test_t1_finger_inside_sentence():
    r = locate_question(LINES, (441, 813), PAGE_H)
    assert r.question_number == 3


def test_t2_finger_on_option_line_no_off_by_one():
    # 회귀 방지 케이스. 최근접 앵커 방식이면 4가 나온다. 반드시 3이어야 한다.
    r = locate_question(LINES, (441, 858), PAGE_H)
    assert r.question_number == 3


def test_t3_finger_at_right_edge_of_sentence():
    r = locate_question(LINES, (637, 813), PAGE_H)
    assert r.question_number == 3


def test_t4_query_text_starts_with_range_header_body():
    r = locate_question(LINES, (441, 813), PAGE_H)
    assert r.query_text.startswith("다음 중 빈칸에 들어갈 말로")


def test_t5_query_text_has_no_anchor_prefix():
    r = locate_question(LINES, (441, 813), PAGE_H)
    assert "3." not in r.query_text


def test_t6_missing_anchor_is_recovered():
    lines_without_anchor3 = [l for l in LINES if l.text != "3."]
    r = locate_question(lines_without_anchor3, (441, 813), PAGE_H)
    assert r.question_number == 3
    assert r.anchor_recovered is True


def test_t7_query_text_excludes_header_and_footer():
    r = locate_question(LINES, (441, 813), PAGE_H)
    assert "2026년도" not in r.query_text
    assert "중졸 (영어)" not in r.query_text


def test_t8_right_column():
    r = locate_question(LINES, (1078, 372), PAGE_H)
    assert r.question_number == 9


def test_t9_range_span():
    r = locate_question(LINES, (441, 813), PAGE_H)
    assert r.range_span == (3, 4)
