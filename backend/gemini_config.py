"""
Gemini API 공용 설정. 파이프라인 안에서 Gemini를 부르는 모듈들은 전부 이 모듈을 거쳐간다.
"""
import os
import re
import json
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

_MODEL_CACHE = {}


def get_model(name="gemini-3.6-flash", json_mode=False):
    """모델 인스턴스를 (이름, json_mode)별로 캐싱해서 재사용한다."""
    key = (name, json_mode)
    if key not in _MODEL_CACHE:
        kwargs = {}
        if json_mode:
            kwargs["generation_config"] = {"response_mime_type": "application/json"}
        _MODEL_CACHE[key] = genai.GenerativeModel(name, **kwargs)
    return _MODEL_CACHE[key]


def parse_json_response(text):
    """
    Gemini 응답 텍스트에서 JSON을 파싱한다. json_mode=True로 호출하면 보통 순수 JSON이
    오지만, 혹시 ```json ... ``` 코드블록으로 감싸서 오는 경우까지 대비해 벗겨내고 파싱한다.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned)
