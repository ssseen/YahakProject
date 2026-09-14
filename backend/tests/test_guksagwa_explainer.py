"""
guksagwa_explainer.py의 problem_text 출처 전환(2026-09-14) 회귀 테스트.
Gemini 호출을 실제로 하지 않고 get_model()을 가짜 모델로 바꿔치기한다.

배경: english_explainer.py와 같은 문제가 국사과 쪽에도 있었다 - question_locator가
잘라준 OCR 텍스트를 화면 표시용 problem_text로 그대로 썼는데, 실사용 중(화학 8번
문제에 9번 보기가 섞이는 등) 다른 문제와 섞이는 사례가 확인됐다. Gemini는 이미지를
직접 보고 이미 올바른 문제를 읽고 있었으므로, Gemini가 옮겨 적은 problem_text를
화면 표시용 원문으로 쓰도록 바꿨다 - 이 전환이 유지되는지 확인한다.
"""
import json
from types import SimpleNamespace
from unittest.mock import patch

import guksagwa_explainer


def _fake_model(parsed: dict):
    return SimpleNamespace(generate_content=lambda parts: SimpleNamespace(text=json.dumps(parsed)))


def test_uses_gemini_transcribed_text_over_wrong_ocr_text():
    # OCR(question_locator)이 다른 문제와 섞어서 잘라온 상황을 재현 (8번+9번 뒤섞임)
    ocr_result = {"ocr_text": "① Zn ② Cu2+ 그림은 주기율표의 일부를... 18 17", "keywords": []}
    gemini_response = {
        "problem_text": "다음 화학 반응식에서 전자를 얻어 환원되는 반응 물질은?\n"
                         "Zn + Cu2+ → Zn2+ + Cu\n① Zn ② Cu2+ ③ Zn2+ ④ Cu",
        "explanation_text": "해설", "answer": "2. Cu2+", "question_number": 8,
    }
    with patch.object(guksagwa_explainer, "get_model", return_value=_fake_model(gemini_response)):
        result = guksagwa_explainer.explain_guksagwa(ocr_result, {"과목": "과학"})

    assert result["problem_text"] == (
        "다음 화학 반응식에서 전자를 얻어 환원되는 반응 물질은?\n"
        "Zn + Cu2+ → Zn2+ + Cu\n① Zn ② Cu2+ ③ Zn2+ ④ Cu"
    )


def test_falls_back_to_ocr_text_when_gemini_omits_problem_text():
    ocr_result = {"ocr_text": "OCR 문제 텍스트", "keywords": []}
    gemini_response = {"explanation_text": "해설", "answer": "1", "question_number": 1}
    with patch.object(guksagwa_explainer, "get_model", return_value=_fake_model(gemini_response)):
        result = guksagwa_explainer.explain_guksagwa(ocr_result, {"과목": "사회"})

    assert result["problem_text"] == "OCR 문제 텍스트"


def test_falls_back_to_ocr_text_when_gemini_gives_empty_string():
    ocr_result = {"ocr_text": "OCR 문제 텍스트", "keywords": []}
    gemini_response = {"problem_text": "  ", "explanation_text": "해설", "answer": "1", "question_number": 1}
    with patch.object(guksagwa_explainer, "get_model", return_value=_fake_model(gemini_response)):
        result = guksagwa_explainer.explain_guksagwa(ocr_result, {"과목": "사회"})

    assert result["problem_text"] == "OCR 문제 텍스트"
