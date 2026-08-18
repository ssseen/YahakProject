"""
정답 텍스트 정규화. 국사과/영어 두 분기가 공용으로 쓴다.

Gemini가 주는 "정답" 원문 형식이 매번 다르다 ("① 6", "3번, 유희[유히]", "(2) 정의",
"정답은 ③번입니다" 등). 프론트는 이걸 파싱하지 않고 {"number": int|None, "text": str}
형태로 받기를 기대하므로(해설 응답 명세서 참고), 여기서 정규식으로 번호와 본문을 분리한다.

re만 import한다 - pipeline.py에 두면 gemini_config(genai.configure) / cv2까지 딸려 들어와서
이 정규식 하나 테스트하는 데도 API 키가 있어야 하는 상황이 되므로, 의존성 없는 별도 모듈로 뺐다.

[번호로 인정하는 마커 - 반드시 명시적 표기가 있어야 함]
맨 앞 숫자를 무조건 번호로 먹으면 "3cm", "6"(그 자체가 답인 경우), "3.14" 같은 본문이
통째로 번호로 오인되어 사라진다. 그래서 아래 명시적 마커가 있을 때만 번호로 인정한다:
  - 동그라미 숫자 (①~⑨)
  - "N번"
  - "(N)"
  - "N." 또는 "N)" 뒤에 공백이 오거나 문자열이 끝나는 경우 (예: "3.14"의 "3."은 뒤에
    바로 숫자가 붙으므로 마커로 인정하지 않음)
맨 앞에 마커가 없으면 문장 중간의 동그라미 숫자를 찾는다 (예: "정답은 ③번입니다") -
이 경우 번호만 채우고 text는 원문 그대로 둔다 (본문에서 숫자를 오려내지 않음).
"""
import re

_CIRCLED_DIGITS = {
    "①": 1, "②": 2, "③": 3, "④": 4, "⑤": 5,
    "⑥": 6, "⑦": 7, "⑧": 8, "⑨": 9,
}

_LEADING_MARKER_RE = re.compile(
    r"""^(?:
        (?P<circled>[①②③④⑤⑥⑦⑧⑨])   |
        \((?P<paren>\d{1,2})\)          |
        (?P<beon>\d{1,2})\s*번           |
        (?P<dot>\d{1,2})[.)](?=\s|$)
    )""",
    re.VERBOSE,
)
_INLINE_CIRCLED_RE = re.compile(r"[①②③④⑤⑥⑦⑧⑨]")
_LEADING_SEP_RE = re.compile(r"^[,.:\-\s]+")
_PLAIN_INT_RE = re.compile(r"^\d{1,2}$")


def _strip_leading_marker(s):
    """
    s 맨 앞에 명시적 번호 마커가 있으면 떼어내고 (번호, 나머지) 를 반환한다.
    마커가 없으면 (None, s)를 그대로 반환한다 (숫자로 시작해도 마커가 없으면 건드리지 않음).
    """
    m = _LEADING_MARKER_RE.match(s)
    if not m:
        return None, s

    if m.group("circled"):
        number = _CIRCLED_DIGITS.get(m.group("circled"))
    elif m.group("paren") is not None:
        number = int(m.group("paren"))
    elif m.group("beon") is not None:
        number = int(m.group("beon"))
    else:
        number = int(m.group("dot"))

    rest = _LEADING_SEP_RE.sub("", s[m.end():]).strip()
    return number, rest


def _search_inline_circled(s):
    """맨 앞 마커가 없을 때, 문장 중간의 동그라미 숫자를 찾아 번호만 뽑아낸다."""
    m = _INLINE_CIRCLED_RE.search(s)
    return _CIRCLED_DIGITS.get(m.group(0)) if m else None


def _coerce_number(value):
    """
    dict로 온 raw["number"]가 int(1)뿐 아니라 문자열("1", "①")로 올 수도 있어서 통일한다.
    bool은 int의 서브클래스라 True/False가 실수로 섞여 들어와도 무시한다.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    s = str(value).strip()
    if not s:
        return None
    if s in _CIRCLED_DIGITS:
        return _CIRCLED_DIGITS[s]
    if _PLAIN_INT_RE.match(s):
        return int(s)
    number, _ = _strip_leading_marker(s)
    return number


def normalize_answer(raw, options=None):
    """
    raw: Gemini가 준 정답 원문. 보통 문자열이지만, explainer가 이미 {"number","text"} 형태의
      dict를 돌려주는 경우도 있어서 그 형태도 처리한다 (text 안에 번호 마커가 중복으로 또
      붙어 있으면 그것도 떼어낸다).
    options: [{"no": int, "text": str}, ...] 문제의 보기 목록 (없으면 None).
      번호는 뽑혔는데 본문이 비면(Gemini가 번호만 준 경우) options에서 같은 번호를 찾아 채운다.
      본문이 비었는데 options에도 그 번호가 없으면, 번호 추출 자체가 잘못된 것으로 보고
      number를 다시 None으로 되돌리고 text를 원문으로 복구한다 (본문이 통째로 사라지는
      것보다 번호 배지가 안 뜨는 게 낫다).

    명시적 마커(동그라미 숫자 / "N번" / "(N)" / "N."·"N)" + 공백|끝)가 없으면 번호를 추측하지
    않는다 - "3cm", "6", "3.14"처럼 본문 자체가 숫자로 시작하는 경우까지 번호로 먹지 않기 위함.
    맨 앞에 마커가 없어도 문장 중간에 동그라미 숫자가 있으면(예: "정답은 ③번입니다") 번호만
    채우고 본문은 원문 그대로 둔다.

    반환: {"number": int|None, "text": str}
    """
    if isinstance(raw, dict):
        num_field = _coerce_number(raw.get("number"))
        text_field = "" if raw.get("text") is None else str(raw.get("text")).strip()
        marker_num, stripped_text = _strip_leading_marker(text_field)
        number = num_field if num_field is not None else marker_num
        text = stripped_text
        original_text = text_field
    else:
        s = "" if raw is None else str(raw).strip()
        marker_num, rest = _strip_leading_marker(s)
        if marker_num is not None:
            number = marker_num
            text = rest
        else:
            number = _search_inline_circled(s)
            text = s
        original_text = s

    if not text and number is not None:
        filled = None
        if options:
            for opt in options:
                if opt.get("no") == number:
                    filled = (opt.get("text") or "").strip()
                    break
        if filled:
            text = filled
        else:
            number = None
            text = original_text

    return {"number": number, "text": text}
