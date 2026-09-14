"""
english_explainer.py의 passage_text/options 출처 전환(2026-09-14) 회귀 테스트.
Gemini 호출을 실제로 하지 않고 get_model()을 가짜 모델로 바꿔치기한다.

배경: question_locator가 잘라준 OCR 텍스트가 실사용 중 다른 문제와 섞이는 사례가
반복됐다(35.jpg 등) - 반면 Gemini는 마킹된 이미지를 직접 보고 정답/해설은 정확히
맞혔다. 그래서 화면 표시용 passage/options 원문의 출처를 OCR 텍스트에서 Gemini가
이미지에서 직접 옮겨 적은 값으로 바꿨다 - 이 전환이 유지되는지 확인한다.
"""
import json
from types import SimpleNamespace
from unittest.mock import patch

import english_explainer


def _fake_model(parsed: dict):
    return SimpleNamespace(generate_content=lambda parts: SimpleNamespace(text=json.dumps(parsed)))


def test_uses_gemini_transcribed_text_over_wrong_ocr_text():
    # OCR(question_locator)이 다른 문제와 섞어서 잘라온 상황을 재현
    ocr_result = {
        "passage_text": "완전히 다른 문제의 지문이 섞여 들어옴",
        "options": [{"no": 1, "text": "다른 문제의 보기 1"}],
    }
    gemini_response = {
        "passage_text": "My father gave me an old painting on my birthday.",
        "options": [
            {"no": 1, "text": "father"}, {"no": 2, "text": "painting"},
            {"no": 3, "text": "birthday"}, {"no": 4, "text": "desk"},
        ],
        "translation": "번역", "option_translations": {}, "vocabulary": {},
        "answer": "2. painting", "explanation_text": "해설", "question_number": 12,
    }
    with patch.object(english_explainer, "get_model", return_value=_fake_model(gemini_response)):
        result = english_explainer.explain_english(ocr_result, {"과목": "영어"})

    assert result["passage"]["text"] == "My father gave me an old painting on my birthday."
    assert [o["text"] for o in result["options"]] == ["father", "painting", "birthday", "desk"]


def test_falls_back_to_ocr_passage_when_gemini_omits_it():
    ocr_result = {"passage_text": "OCR 지문", "options": [{"no": 1, "text": "OCR 보기"}]}
    gemini_response = {
        "translation": "번역", "option_translations": {}, "vocabulary": {},
        "answer": "1", "explanation_text": "해설", "question_number": 1,
    }
    with patch.object(english_explainer, "get_model", return_value=_fake_model(gemini_response)):
        result = english_explainer.explain_english(ocr_result, {"과목": "영어"})

    assert result["passage"]["text"] == "OCR 지문"
    assert result["options"][0]["text"] == "OCR 보기"


def test_falls_back_to_ocr_options_when_gemini_gives_empty_list():
    ocr_result = {"passage_text": "지문", "options": [{"no": 1, "text": "OCR 보기"}]}
    gemini_response = {
        "passage_text": "지문", "options": [],
        "translation": "번역", "option_translations": {}, "vocabulary": {},
        "answer": "1", "explanation_text": "해설", "question_number": 1,
    }
    with patch.object(english_explainer, "get_model", return_value=_fake_model(gemini_response)):
        result = english_explainer.explain_english(ocr_result, {"과목": "영어"})

    assert result["options"][0]["text"] == "OCR 보기"
