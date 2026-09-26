"""
4단계(수학 분기): 수학 문제 해설. Gemini 2차 호출.
단계별 풀이(3~5단계, Gemini가 적정 단계 수 결정)를 생성하고, 정답은 마지막 단계에서만 공개한다.

해설에 그림이 필요한 경우, matplotlib으로 그래프/도형을 새로 생성한다. 원본 문제에 그림이
있으면 그 내용을 참고해 비슷하게 재현하고 강조점을 표시하며, 원본에 그림이 없으면 문제에
맞는 그래프/도형을 새로 구성한다. (원래는 원본 이미지 위에 Pillow로 오버레이를 그리는 방식도
시도했으나, Gemini가 이미지 속 정확한 픽셀 좌표를 짚어내는 정확도가 낮아 - 2026-09-27 확인 -
matplotlib 생성 방식으로 통일함. Pillow/overlay 관련 코드는 이 통일 과정에서 제거됨.)
"""
import os
import uuid

import cv2

from gemini_config import get_model, parse_json_response

_DIAGRAM_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "diagrams")
os.makedirs(_DIAGRAM_DIR, exist_ok=True)

_BASE_PROMPT_TEMPLATE = """
당신은 야학 어르신을 위한 수학 선생님입니다.

[규칙]
- 쉬운 우리말 사용, 친근한 말투
- 풀이는 3~5단계로 나누세요. 단계 수는 문제 난이도에 맞게 직접 정하세요.
- 정답은 반드시 "마지막 단계"에서만 공개하세요. 그 전 단계에서는 정답을 언급하거나
  암시하지 마세요.
- 수식은 LaTeX 문법($, \\frac, ^ 등)을 쓰지 말고, 일반 텍스트로 풀어 쓰세요.
  예: "x²" 대신 "x의 제곱", 또는 "x^2"처럼 캐럿 기호만 사용하고 달러 기호는 쓰지 마세요.
- 아래 JSON 형식으로만 답하세요. 다른 설명, 마크다운 코드블록 없이 순수 JSON만 출력하세요.

{{
  "problem_text": "빨간 박스 안, 실제 풀어야 할 문제의 지문/발문/보기를 이미지에 보이는 그대로 옮겨 적으세요. 제곱, 첨자 등도 놓치지 말고 옮기되, LaTeX 기호($, ^)는 쓰지 말고 '(x-1)의 제곱'처럼 우리말로 풀어 쓰세요.",
  "steps": [
    {{"step_number": 1, "text": "1단계 설명 (정답 언급 금지)"}},
    {{"step_number": 2, "text": "2단계 설명 (정답 언급 금지)"}},
    ...
    {{"step_number": N, "text": "마지막 단계 설명 + 정답 공개"}}
  ],
  "answer": "정답 번호와 내용",
  "needs_diagram": true 또는 false,
  "diagram_spec": {{ ... }},
  "question_number": 실제로 풀이한 문제 번호(정수)
}}

[diagram_spec 작성 규칙]
needs_diagram이 true이면, matplotlib으로 그릴 수 있는 그래프/도형 정보를 diagram_spec에
담으세요. 문제에 원본 그림이 있다면 그 그림의 핵심 내용(함수 모양, 좌표, 도형 등)을
최대한 비슷하게 재현하고, 강조하고 싶은 지점(예: 최솟값 꼭짓점)을 highlights에 표시하세요.
원본에 그림이 없다면 문제 내용에 맞는 그래프/도형을 새로 구성하세요.

diagram_spec 형식 (수학적 좌표 기준입니다 - 이미지 픽셀 좌표가 아닙니다):
{{
  "chart_type": "function" 또는 "scatter" 또는 "shape",
  "function_expr": "이차함수 등 그래프의 수식을 파이썬 문법으로 작성 (예: (x - 1)**2 - 2)",
  "x_range": [최소x, 최대x],
  "solid_range": [최소x, 최대x],
  "labels": {{"x": "x축 이름", "y": "y축 이름"}},
  "highlights": [{{"point": [x, y], "label": "이 점에 대한 설명"}}]
}}
- chart_type이 "function"이면 반드시 function_expr에 x에 대한 수식을 파이썬 문법으로
  작성하세요 (예: "x**2 - 2*x + 1", "(x - 1)**2 - 2"). ^ 대신 **를 쓰고, x라는 변수명을
  그대로 쓰세요.
- x_range는 그래프에 표시할 전체 x 범위입니다 (점선 구간 포함).
- solid_range는 문제에서 정의역으로 제한한 범위(예: 0≤x≤3)가 있으면 그 범위를 실선으로,
  나머지는 점선으로 표시하기 위한 값입니다. 범위 제한이 없으면 x_range와 같은 값을 쓰세요.
- chart_type이 "scatter"인 경우에만 data에 {{"x": [...], "y": [...]}} 형태로 개별 점들을 주세요.

그림이 필요 없으면 needs_diagram: false, diagram_spec: {{}}

만약 이 문제가 [문제 유형]에 지정된 과목이 명백히 아니라면:
{{"subject_mismatch": "이 문제의 올바른 과목명"}}

[문제 유형]
과목: {subject}
"""

_MARKED_IMAGE_HINT = (
    "첨부한 이미지는 문제지 페이지 전체이며, 지금 풀어야 할 문제는 빨간 박스로 표시돼 있습니다. "
    "빨간 박스 안의 문제만 푸세요."
)


def explain_math(ocr_result, classification, marked_image=None, user_question="이 문제 좀 알려줘",
                  *, range_header=None, low_conf_lines=None,
                  subject_hint=None, category=None, transcript=None, reference=None):
    """
    반환: {"steps": [...], "answer": str, "diagram_path": str|None,
           "explanation_text": str, "question_number": int|None, "subject_mismatch": str|None}
    """
    prompt = _BASE_PROMPT_TEMPLATE.format(
        subject=classification.get("과목", ""),
    )
    if user_question:
        prompt += f'\n[질문]\n"{user_question}"\n'

    parts = [prompt]
    if marked_image is not None:
        ok, buf = cv2.imencode(".jpg", marked_image)
        if ok:
            parts = [{"mime_type": "image/jpeg", "data": buf.tobytes()}, _MARKED_IMAGE_HINT, prompt]

    model = get_model(json_mode=True)
    response = model.generate_content(parts)
    parsed = parse_json_response(response.text)

    if parsed.get("subject_mismatch"):
        return {"subject_mismatch": parsed["subject_mismatch"]}

    steps = parsed.get("steps", [])
    # explanation_text: 다른 explainer와 동일하게 화면+음성 통합 텍스트 하나로 합침
    explanation_text = " ".join(s.get("text", "") for s in steps)

    diagram_path = None
    if parsed.get("needs_diagram"):
        spec = parsed.get("diagram_spec", {})
        diagram_path = generate_diagram(spec)

    return {
        "problem_text": parsed.get("problem_text", ""),
        "steps": steps,
        "explanation_text": explanation_text,
        "answer": parsed.get("answer", ""),
        "diagram_path": diagram_path,
        "question_number": parsed.get("question_number"),
        "subject_mismatch": None,
    }


def generate_diagram(spec):
    """matplotlib으로 그래프/도형을 새로 그려서 PNG로 저장, URL 경로 반환.
    원본 문제에 그림이 있었으면 그 내용을 재현+강조한 것이고, 없었으면 새로 구성한 것이다
    (원본/재현 여부는 Gemini가 diagram_spec 내용 자체로 반영하며, 이 함수는 구분하지 않는다).

    chart_type="function"이면 Gemini가 준 수식(function_expr)을 numpy로 촘촘히(200개 점)
    계산해서 그린다 - 처음엔 Gemini가 준 (x,y) 좌표 배열을 그대로 그렸으나, 점 개수가 성겨서
    구간에 따라 직선처럼 어색하게 이어지는 문제가 있어(2026-09-27 확인) 수식 기반으로 바꿨다."""
    print("DEBUG diagram_spec (generate):", spec)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm
    import numpy as np

    plt.rcParams["axes.unicode_minus"] = False

    _KOREAN_FONT_CANDIDATES = ["AppleGothic", "Malgun Gothic", "NanumGothic", "Noto Sans CJK KR"]
    available_fonts = {f.name for f in fm.fontManager.ttflist}
    for font_name in _KOREAN_FONT_CANDIDATES:
        if font_name in available_fonts:
            plt.rcParams["font.family"] = font_name
            break
    else:
        print("경고: 한글 폰트를 찾지 못해 라벨이 깨질 수 있음")

    fig, ax = plt.subplots()
    chart_type = spec.get("chart_type")
    labels = spec.get("labels", {})

    if chart_type == "function" and spec.get("function_expr"):
        x_range = spec.get("x_range", [-5, 5])
        solid_range = spec.get("solid_range", x_range)
        expr = spec["function_expr"]

        xs = np.linspace(x_range[0], x_range[1], 200)
        try:
            ys = eval(expr, {"__builtins__": {}}, {"x": xs, "np": np})
        except Exception as e:
            print(f"경고: function_expr 계산 실패({e!r}), 그래프 생성 건너뜀: {expr}")
            plt.close(fig)
            return None

        lo, hi = solid_range
        solid_mask = (xs >= lo) & (xs <= hi)
        ax.plot(xs[solid_mask], ys[solid_mask], "-", color="black", linewidth=2)
        left_mask = xs < lo
        right_mask = xs > hi
        if left_mask.any():
            ax.plot(xs[left_mask], ys[left_mask], "--", color="black", linewidth=1.5)
        if right_mask.any():
            ax.plot(xs[right_mask], ys[right_mask], "--", color="black", linewidth=1.5)

    elif chart_type == "scatter":
        data = spec.get("data", {})
        ax.scatter(data.get("x", []), data.get("y", []), color="black")

    # 원점을 지나는 x축/y축
    ax.axhline(0, color="black", linewidth=1)
    ax.axvline(0, color="black", linewidth=1)

    # 강조점 + 좌표까지 안내 점선
    for h in spec.get("highlights", []):
        point = h.get("point")
        if point and len(point) == 2:
            hx, hy = point
            ax.plot(hx, hy, "o", color="black", markersize=6)
            ax.plot([hx, hx], [0, hy], linestyle=":", color="gray", linewidth=1)
            ax.plot([0, hx], [hy, hy], linestyle=":", color="gray", linewidth=1)
            label = h.get("label", "")
            if label:
                ax.annotate(label, (hx, hy), textcoords="offset points",
                            xytext=(8, 8), color="black")

    ax.set_xlabel(labels.get("x", "x"))
    ax.set_ylabel(labels.get("y", "y"), rotation=0)
    ax.grid(True, linestyle="--", alpha=0.3)

    filename = f"diagram_{uuid.uuid4().hex}.png"
    out_path = os.path.join(_DIAGRAM_DIR, filename)
    fig.savefig(out_path)
    plt.close(fig)
    return f"/diagrams/{filename}"