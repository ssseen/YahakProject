"""
3단계: 문제 유형 분류. 아직 Pinecone 연동 전이라 목업(mock)이다.

세연님이 실제 Pinecone 기반 분류 스펙을 주면 classify_problem() 함수 내부만 통째로
교체하면 된다 - 인터페이스(입력: OCR 텍스트, 출력: {"과목", "대분류", "중분류"})만 유지하면
파이프라인의 나머지 부분은 안 건드려도 된다.
"""
import re

_SOCIAL_KEYWORDS = ["헌법", "국회", "정부", "선거", "지방자치", "법률", "국민"]
_SCIENCE_KEYWORDS = ["세포", "광합성", "원소", "화학", "생태계", "전류", "에너지"]


def classify_problem(ocr_text, mock_override=None):
    """
    ocr_text: 1차 Gemini 호출(extract_problem_info)에서 나온 문제 지문 텍스트.
    mock_override: 지정하면 분류를 거치지 않고 그대로 반환한다. Pinecone 연동 전에
      파이프라인의 다른 단계(국사과 분기 등)를 테스트할 때 쓴다.

    지금 내부 로직은 아주 단순한 키워드 규칙일 뿐이라 실제 정확도는 없다 - 나중에
    Pinecone 결과로 통째로 교체될 자리표시자(placeholder)다.

    반환: {"과목": str, "대분류": str, "중분류": str}
    """
    if mock_override is not None:
        return mock_override

    text = ocr_text or ""

    if re.search(r"[0-9]\s*[xX]|[+\-×÷]|=\s*[0-9]", text):
        return {"과목": "수학", "대분류": "미분류", "중분류": "미분류"}
    if re.search(r"[A-Za-z]{4,}", text) and re.search(r"\b[AB]\s*:", text):
        return {"과목": "영어", "대분류": "미분류", "중분류": "미분류"}
    if any(k in text for k in _SCIENCE_KEYWORDS):
        return {"과목": "과학", "대분류": "미분류", "중분류": "미분류"}
    if any(k in text for k in _SOCIAL_KEYWORDS):
        return {"과목": "사회", "대분류": "정치", "중분류": "헌법"}

    # 아무 키워드에도 안 걸리면 근거가 없는 것 - "사회"라고 단정짓지 않고 정직하게 미분류 처리.
    return {"과목": "미분류", "대분류": "미분류", "중분류": "미분류"}
