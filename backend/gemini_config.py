"""
Gemini API 공용 설정. 파이프라인 안에서 Gemini를 부르는 모듈들은 전부 이 모듈을 거쳐간다.
"""
import os
import re
import json
import time
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

_MODEL_CACHE = {}

# 세 explainer(국사과/영어/수학) 공용 이미지 안내문 (2026-10-26).
# 예전엔 "빨간 박스 안의 문제만 풀고 박스 밖은 절대 참고하지 마라"였는데, 박스는 손끝 좌표로
# 근사한 영역이라 문제 일부만 감싸거나 옆 문제가 섞이는 경우가 있다 - 그때 Gemini가 박스에
# 갇혀서 잘린 문제를 풀었다. 이제 박스는 "어느 문제인지" 알려주는 표시로만 쓰고, 문제의
# 범위는 Gemini가 이미지를 보고 직접 판단하게 한다.
MARKED_IMAGE_HINT = (
    "첨부한 이미지는 문제지 페이지 전체입니다. 빨간 박스는 학생이 손가락으로 가리킨 위치를 "
    "바탕으로 프로그램이 대략 표시한 영역이라 정확하지 않을 수 있습니다(문제 일부만 감싸거나, "
    "옆 문제가 섞여 들어가 있을 수 있음). 빨간 박스가 가장 많이 덮고 있는 문제 하나를 찾아서, "
    "그 문제의 발문·지문·보기·그림/표 전체(박스 밖으로 이어진 부분 포함)를 기준으로 푸세요. "
    "여러 문제가 함께 쓰는 공통 지시문이나 지문(예: '[3~4] 다음 글을 읽고')이 있으면 그것도 "
    "참고하세요. 그 밖의 다른 문제는 참고하지 마세요. 답변은 지시한 JSON 형식으로만 하고, "
    "이미지를 그리거나 다시 첨부하지 마세요."
)

# 음성 질문 처리 규칙 - 국사과/영어 explanation_text용 (수학은 steps 구조라 자체 규칙을 둔다).
VOICE_QUESTION_RULES = """[음성 질문 처리 규칙 - 가장 중요]
- 맨 아래 [음성 질문]이 학생이 실제로 궁금해하는 것입니다. 문제 해설보다 이 질문에 답하는 것이 우선입니다.
- "이 문제 알려줘", "풀어줘", "설명해줘"처럼 문제 풀이 전체를 원하는 일반적인 요청이면 질문을
  되짚지 말고 바로 문제 해설을 쓰세요 (되짚으면 "설명해달라고 하셨죠, 설명하면"처럼 순환이 됩니다).
- 단어 뜻, 특정 보기, 특정 개념, 왜 그게 답인지 같은 구체적인 질문이면 explanation_text 맨 앞에서
  그 질문에 먼저 충분히 답하세요(인식된 문장을 그대로 인용하지 말고 자연스럽게 풀어서). 그 다음에
  문제 풀이를 짧게 이어 쓰세요.
- 음성 인식 결과가 깨져서 무슨 뜻인지 알 수 없거나, 이 문제·공부와 전혀 상관없는 말이면 질문을
  되짚거나 지어내지 말고 문제 해설만 쓰세요 - 깨진 인식 결과로 없는 질문을 지어내는 것이 가장 나쁜 실패입니다.
- 어떤 질문이든 answer 필드는 항상 채우세요.
"""


def voice_question_section(question):
    """음성 질문을 프롬프트 맨 끝에 한 번만 붙이는 블록. 질문이 없으면 빈 문자열."""
    if not question:
        return ""
    return f'\n[음성 질문 - 학생이 음성으로 물어본 내용]\n"{question}"\n'


def get_model(name="gemini-3.6-flash", json_mode=False):
    """모델 인스턴스를 (이름, json_mode)별로 캐싱해서 재사용한다."""
    key = (name, json_mode)
    if key not in _MODEL_CACHE:
        kwargs = {}
        if json_mode:
            kwargs["generation_config"] = {
                "response_mime_type": "application/json",
                "temperature": 0.2,
            }
        _MODEL_CACHE[key] = genai.GenerativeModel(name, **kwargs)
    return _MODEL_CACHE[key]


def timed_generate(model, parts):
    """
    generate_content를 부르고 (response, 측정값)을 반환한다 - 속도 측정용(2026-10-26).
    측정값: 걸린 시간(초)과 usage_metadata의 토큰 수. thinking_tokens는 모델이 답하기 전에
    속으로 생각하는 데 쓴 토큰(응답 텍스트엔 안 보이지만 시간은 든다). SDK/모델에 따라
    없는 필드는 None.
    """
    t0 = time.perf_counter()
    response = model.generate_content(parts)
    usage = getattr(response, "usage_metadata", None)

    def _tok(name):
        v = getattr(usage, name, None)
        return v if isinstance(v, int) else None

    info = {
        "seconds": round(time.perf_counter() - t0, 3),
        "prompt_tokens": _tok("prompt_token_count"),
        "output_tokens": _tok("candidates_token_count"),
        "thinking_tokens": _tok("thoughts_token_count"),
        "total_tokens": _tok("total_token_count"),
    }
    return response, info


def generate_json(model, parts, retries=1):
    """
    Gemini를 부르고 JSON으로 파싱해 (parsed, 측정값)을 반환한다. JSON 모드여도 Gemini가 가끔
    형식이 깨진 JSON(쉼표 누락 등)을 보내는데(2026-10-26 속도측정 hand_one4 실측), 그대로 두면
    사용자가 녹음까지 마친 뒤 에러 화면을 본다 - 파싱에 실패하면 retries번 다시 부른다.
    측정값의 seconds/토큰은 모든 시도를 합친 값, json_retries는 다시 부른 횟수.
    """
    total = None
    for attempt in range(retries + 1):
        response, info = timed_generate(model, parts)
        if total is None:
            total = info
        else:
            for k in ("seconds", "prompt_tokens", "output_tokens", "thinking_tokens", "total_tokens"):
                if isinstance(total.get(k), (int, float)) and isinstance(info.get(k), (int, float)):
                    total[k] = round(total[k] + info[k], 3)
        total["json_retries"] = attempt
        try:
            return parse_json_response(response.text), total
        except json.JSONDecodeError as e:
            print(f"경고: Gemini 응답 JSON 파싱 실패({e}) - "
                  f"{'다시 호출' if attempt < retries else '재시도 소진'}. 응답 앞부분: {response.text[:200]!r}")
            if attempt == retries:
                raise


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
