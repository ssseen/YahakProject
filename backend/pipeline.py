"""
국어/사회/과학(국사과)/영어 해설 파이프라인 - 엔드투엔드 오케스트레이션. v2.

  1) 이미지를 장축 1960px로 리사이즈 (Clova 권장 해상도, 이후 모든 좌표의 공통 기준)
  2) 리사이즈된 이미지에서 손끝을 다시 검출 (find_finger_tip) - main.py가 넘겨준 x,y는
     원본 이미지 좌표라 그대로 못 쓴다. 배율 변환 수식을 쓰는 대신, 이미 리사이즈된
     이미지에서 다시 검출해서 애초에 좌표계를 하나로 맞춘다 (변환 버그 여지 자체를 제거).
  3) Clova OCR 호출 -> 줄 목록(app.clova_client.to_lines)
  4) question_locator로 손끝이 가리키는 문항 특정 (번호 앵커 + 밴드, 자르지 않고 표시만)
  5) Pinecone 무필터 검색 1회 (top_k=10) -> 같은 결과를 과목 판정과 유사문제 선별에 나눠 씀
  6) subject_router로 과목(영어/수학/국사과) 판정
  7) 국어/사회/과학이면 explain_guksagwa로, 영어면 explain_english로 Gemini 2차 호출
     (v2의 유일한 LLM 호출). 수학은 아직 미지원.
  8) 과목 자가검증(subject_mismatch) 처리 + 문항번호 자가검증 로그
  9) 최종 JSON 조립

Gemini 1차 호출은 v2에서 완전히 제거됐다 (problem_extractor.py는 backend/experiments/로
이동 - EasyOCR 비교 실험의 비교 대상으로 계속 쓰이므로 삭제하지 않음, pipeline.py에서는
더 이상 import하지 않는다).
"""
import json
import re
import time

import cv2
import numpy as np
from dotenv import load_dotenv
from pinecone import Pinecone
import os

from vision_processor import find_finger_tip
from app.clova_client import resize_for_ocr, call_clova, to_lines, ClovaError
from app.question_locator import locate_question, LocateError
from app.subject_router import decide_branch, select_similar, BRANCH_OF
from guksagwa_explainer import explain_guksagwa
from english_explainer import explain_english
from answer_utils import normalize_answer

load_dotenv()

_PINECONE_INDEX_NAME = "geondi-questions"
_PINECONE_NAMESPACE = "questions"
_PINECONE_TOP_K = 10

_OPTION_MARKERS = "①②③④⑤"


def _marker_pattern(n: int):
    """n번 보기 마커 패턴 - 원문자(①~⑤) 또는, Clova가 원문자를 못 읽고 맨 숫자로
    반환한 경우를 대비해 공백으로 둘러싸인 숫자 n도 같이 허용한다 (실제로 ④가
    "4"로 인식돼 보기 3번 텍스트 뒤에 붙어버리는 사례가 있었음)."""
    circled = _OPTION_MARKERS[n - 1]
    return re.compile(rf"{re.escape(circled)}|(?<=\s){n}(?!\d)(?=\s)")

_RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")

_pinecone_index = None


def _get_pinecone_index():
    """Pinecone Index 클라이언트를 lazy하게 생성해 캐싱한다 (classifier.py와 같은 패턴이지만,
    무필터 검색이라 별도 클라이언트로 둔다 - classifier.py는 건드리지 않기로 했음)."""
    global _pinecone_index
    if _pinecone_index is None:
        api_key = os.getenv("PINECONE_API_KEY")
        if not api_key:
            raise RuntimeError("PINECONE_API_KEY가 .env에 설정되지 않음")
        _pinecone_index = Pinecone(api_key=api_key).Index(_PINECONE_INDEX_NAME)
    return _pinecone_index


def _search_unfiltered(query_text):
    """
    Pinecone 무필터 검색 1회 (top_k=10). 이 결과를 subject_router.decide_branch(과목 판정)와
    select_similar(유사문제 선별) 양쪽에 그대로 나눠 쓴다 - 절대 두 번 호출하지 않는다.
    필터를 안 거는 이유: 메타데이터 필터에 subject가 필요한데 subject를 얻으려고 이 검색을
    하는 것이므로 순환이기 때문 (app/subject_router.py 모듈 docstring 참고).
    """
    index = _get_pinecone_index()
    res = index.search(
        namespace=_PINECONE_NAMESPACE,
        query={"inputs": {"text": query_text}, "top_k": _PINECONE_TOP_K},
    )
    result = getattr(res, "result", res)
    hits = getattr(result, "hits", None)
    if hits is None and isinstance(result, dict):
        hits = result.get("hits")
    return list(hits or [])


def _split_passage_and_options(text):
    """
    question_locator가 만든 query_text(범위 지시문 + 지문/발문 + 보기가 한 문자열로 합쳐진 것)를
    영어 분기 explainer가 요구하는 passage_text/options 형태로 다시 나눈다. ①이 처음 나오는
    지점을 기준으로 그 앞을 지문, 그 뒤를 보기로 본다. 국사과 분기는 이 분리가 필요 없어
    ocr_text(=query_text 그대로)만 쓴다.
    """
    first_marker_idx = min(
        (text.index(m) for m in _OPTION_MARKERS if m in text), default=-1
    )
    if first_marker_idx == -1:
        return text.strip(), []

    passage = text[:first_marker_idx].strip()
    remainder = text[first_marker_idx:]

    # ①은 이미 remainder[0]에 있는 것으로 확정. ②~⑤는 원문자든 맨 숫자든 순서대로
    # 하나씩 찾는다 - "다음 마커가 몇 번인지 미리 안다"는 전제로 찾기 때문에, 보기
    # 본문에 우연히 등장하는 숫자와 혼동할 위험이 원문자/맨숫자 구분 없는 방식보다 낮다.
    positions = [0]
    for n in range(2, 6):
        m = _marker_pattern(n).search(remainder, positions[-1] + 1)
        if m is None:
            break
        positions.append(m.start())
    positions.append(len(remainder))

    options = []
    for i in range(len(positions) - 1):
        chunk = remainder[positions[i]:positions[i + 1]]
        opt_text = chunk
        for m in _OPTION_MARKERS:
            opt_text = opt_text.replace(m, "")
        opt_text = re.sub(r"^\s*\d+\s*", "", opt_text)  # 맨 숫자 마커였던 경우 그 숫자도 제거
        options.append({"no": i + 1, "text": opt_text.strip()})
    return passage, options


def _bbox_overlaps(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    return ax1 < bx2 and ax2 > bx1 and ay1 < by2 and ay2 > by1


def _low_conf_texts_in_box(clova_lines, low_conf_indices, box):
    """페이지 전체 기준 low_conf_lines(인덱스)를, 지금 문항의 box 안에 있는 줄의 텍스트만
    걸러서 explainer에 넘긴다 (인덱스 자체는 explainer가 알 이유가 없음)."""
    out = []
    for i in low_conf_indices:
        if i < len(clova_lines) and _bbox_overlaps(clova_lines[i].bbox, box):
            out.append(clova_lines[i].text)
    return out


def _category_hint_for_branch(matches, branch):
    """matches 중 branch에 속하는 첫 hit의 category_large/category_mid로 유형 힌트 문자열을
    만든다 (없으면 None). subject_router는 category_large를 분류 판단에 안 쓰지만, 여기는
    Gemini에게 주는 참고용 힌트일 뿐이라 상관없다."""
    for m in matches:
        fields = getattr(m, "fields", None) or {}
        subj = fields.get("subject")
        if subj in BRANCH_OF and BRANCH_OF[subj] == branch:
            large = fields.get("category_large", "")
            mid = fields.get("category_mid", "")
            if large or mid:
                return f"{large} > {mid}"
            return None
    return None


def _format_similar_questions(matches):
    out = []
    for m in matches:
        fields = getattr(m, "fields", None) or {}
        out.append({
            "id": getattr(m, "id", None),
            "score": getattr(m, "score", None),
            "text": fields.get("text", ""),
            "answer": fields.get("answer"),
            "explanation": fields.get("explanation", ""),
            "year": fields.get("year"),
            "exam_round": fields.get("exam_round"),
            "question_number": fields.get("question_number"),
        })
    return out


def _retake_response(reason, blur_score=None, brightness=None):
    """retake 응답 스키마를 하나로 통일한다. 해당 없는 값은 null."""
    return {
        "status": "retake",
        "reason": reason,
        "blur_score": blur_score,
        "brightness": brightness,
        "skew_deg": None,  # vision_processor.py를 건드리지 않는 한 계산할 수 없음
        "text_object_count": None,  # 위와 동일
    }


def _explainer_for(branch):
    return explain_english if branch == "영어" else explain_guksagwa


def run_pipeline(image_path, x, y, stt_text=None, user_question="이 문제 좀 알려줘",
                  classification_override=None, save_path=None):
    """
    image_path: 문제지 사진 파일 경로.
    x, y: main.py(analyze_image)가 원본 이미지에서 찾은 손끝 픽셀 좌표 - v2에서는 "손끝이
      있었는지 여부"만 신호로 쓰고, 실제 좌표는 이 함수 내부에서 1960px로 리사이즈한
      이미지에 대해 find_finger_tip을 다시 돌려서 얻는다 (배율 변환 코드 없이 좌표계를
      하나로 맞추기 위함). 원본에서 손끝을 못 찾았으면(x, y가 둘 다 None) 이 함수도 처음부터
      재검출을 시도하지 않는다.
    stt_text: 학생이 음성으로 한 질문 (없으면 None) - Gemini 2차 호출의 transcript로 전달됨.
    classification_override: {"과목": str, ...} 형태로 주면 Pinecone/subject_router를 건너뛰고
      해당 과목의 브랜치로 강제 진행한다 (하위 호환용 테스트 편의 기능, test_pipeline.py 참고).
    save_path: 지정하면 최종 결과를 JSON 파일로도 저장한다.

    반환 (해설 응답 명세서 - 국사과/영어 분기 참고):
      국사과 성공 시 {"status": "success", "type": "guksagwa", "subject": str,
                    "problem_type": str, "problem_text": str, "explanation": str,
                    "answer": {"number": int|None, "text": str}, ...}
      영어 성공 시   {"status": "success", "type": "english", "subject": str,
                    "problem_type": str, "passage": {...}, "options": [...],
                    "translation": {...}, "explanation": str,
                    "answer": {"number": int|None, "text": str}, ...}
      미지원 과목    {"status": "unsupported_subject", "subject": str, "message": str}
      재촬영 요청    {"status": "retake", "reason": str, "blur_score", "brightness",
                    "skew_deg", "text_object_count"} (해당 없는 값은 null)
      오류 시        {"status": "error", "message": str}  (HTTP 500이 아니라 200으로 나감 -
                    main.py가 이 함수가 반환한 dict를 그대로 JSON 응답으로 돌려주기 때문에,
                    여기서 예외를 밖으로 던지지만 않으면 자동으로 200이 된다)

    성공 응답에는 공통으로 finger_detected, illustration_attached(marked_image 첨부 여부),
    branch, subject_hint, agreement, guard, fallback_level, locate_confidence,
    anchor_recovered, similar_questions, below_threshold가 붙는다.
    """
    pipeline_start = time.perf_counter()

    try:
        result = _run_pipeline_inner(image_path, x, y, stt_text, user_question,
                                      classification_override)
    except Exception as e:
        print(f"오류: 파이프라인 처리 중 예외 발생: {e!r}")
        result = {"status": "error", "message": str(e)}

    print(f"전체 소요 시간: {time.perf_counter() - pipeline_start:.2f}초")

    # save_path를 안 줘도(main.py는 안 줌) 매 요청 결과를 backend/results/에 자동 저장한다.
    # 그전엔 API로 들어온 요청은 응답만 하고 사라져서 나중에 다시 볼 방법이 없었다.
    auto_path = os.path.join(_RESULTS_DIR, f"{time.strftime('%Y%m%d_%H%M%S')}_{os.getpid()}.json")
    os.makedirs(_RESULTS_DIR, exist_ok=True)
    with open(auto_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"결과 저장됨: {auto_path}")

    if save_path:
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

    return result


def _run_pipeline_inner(image_path, x, y, stt_text, user_question, classification_override):
    t_resize = time.perf_counter()
    try:
        resized_bytes, page_w, page_h = resize_for_ocr(image_path)
    except Exception as e:
        return {"status": "error", "message": f"이미지를 읽을 수 없음: {e}"}

    resized_img = cv2.imdecode(np.frombuffer(resized_bytes, np.uint8), cv2.IMREAD_COLOR)
    if resized_img is None:
        return {"status": "error", "message": "이미지 디코딩 실패"}
    print(f"0. 이미지 리사이즈 (장축 1960px, {page_w}x{page_h}) 완료 "
          f"({time.perf_counter() - t_resize:.2f}초)")

    finger_detected = x is not None and y is not None
    fx, fy = None, None
    if finger_detected:
        tip, tip_msg = find_finger_tip(resized_img)
        if tip is not None:
            fx, fy = tip["x"], tip["y"]
        else:
            print(f"경고: 원본에서는 손끝을 찾았으나 리사이즈본에서는 재검출 실패({tip_msg}) "
                  "- 손끝 없음으로 처리")
            finger_detected = False

    if not finger_detected:
        return _retake_response(reason="no_finger")

    print("1. Clova OCR 호출...")
    t_ocr = time.perf_counter()
    try:
        clova_response = call_clova(resized_bytes)
    except ClovaError as e:
        return {"status": "error", "message": f"OCR 호출 실패: {e}"}
    ocr_data = to_lines(clova_response)
    print(f"   줄 {len(ocr_data['lines'])}개, page_conf_min={ocr_data['page_conf_min']} "
          f"({time.perf_counter() - t_ocr:.2f}초)")

    if not ocr_data["lines"]:
        return _retake_response(reason="no_text")

    print("2. 문항 특정 (question_locator)...")
    t_locate = time.perf_counter()
    try:
        locate_result = locate_question(ocr_data["lines"], (fx, fy), page_h)
    except LocateError as e:
        print(f"경고: 문항 특정 실패: {e}")
        return _retake_response(reason="location_failed")
    print(f"   -> {locate_result.question_number}번, "
          f"confidence={locate_result.locate_confidence}, "
          f"fallback_level={locate_result.fallback_level}, "
          f"anchor_recovered={locate_result.anchor_recovered} "
          f"({time.perf_counter() - t_locate:.2f}초)")
    # [로그] 필수 필드
    print(f"   [로그] fallback_level={locate_result.fallback_level} "
          f"locate_confidence={locate_result.locate_confidence} "
          f"anchor_recovered={locate_result.anchor_recovered} "
          f"page_conf_min={ocr_data['page_conf_min']}")

    print("3. Pinecone 검색 (무필터, top_k=10)...")
    t_search = time.perf_counter()
    if classification_override is not None:
        matches = []
        branch_result = None
        branch = BRANCH_OF.get(classification_override.get("과목"), "국사과")
        subject_hint = classification_override.get("과목")
        agreement, vote_count, guard = 1.0, 0, "override"
        print(f"   classification_override로 강제 지정: branch={branch}")
    else:
        matches = _search_unfiltered(locate_result.query_text)
        branch_result = decide_branch(matches, locate_result.query_text)
        branch = branch_result.branch
        subject_hint = branch_result.subject_hint
        agreement, vote_count, guard = (branch_result.agreement, branch_result.vote_count,
                                         branch_result.guard)
    print(f"   -> branch={branch}, subject_hint={subject_hint}, agreement={agreement}, "
          f"guard={guard} ({time.perf_counter() - t_search:.2f}초)")
    # [로그] 필수 필드
    print(f"   [로그] agreement={agreement} vote_count={vote_count} guard={guard}")

    similar_questions = _format_similar_questions(select_similar(matches, branch, exclude_id=None))
    below_threshold = not similar_questions
    category = _category_hint_for_branch(matches, branch)

    box = locate_result.box
    marked_img = resized_img.copy()
    cv2.rectangle(marked_img, (box[0], box[1]), (box[2], box[3]), (0, 0, 255), 4)

    low_conf_lines = _low_conf_texts_in_box(ocr_data["lines"], ocr_data["low_conf_lines"], box)

    passage, options_v2 = _split_passage_and_options(locate_result.query_text)
    ocr_result_guksagwa = {"ocr_text": locate_result.query_text, "keywords": []}
    ocr_result_english = {
        "ocr_text": locate_result.query_text,
        "passage_text": passage,
        "options": options_v2,
    }

    reference = None
    if similar_questions:
        top = similar_questions[0]
        reference = {"answer": top.get("answer"), "explanation": top.get("explanation")}

    common_kwargs = dict(
        marked_image=marked_img,
        user_question=user_question,
        range_header=locate_result.range_header,
        low_conf_lines=low_conf_lines or None,
        subject_hint=subject_hint,
        category=category,
        transcript=stt_text,
        reference=reference,
    )

    if branch == "수학":
        # 수학 해설기는 아직 구현되지 않음 (v1과 동일하게 미지원으로 응답)
        result = {
            "status": "unsupported_subject",
            "subject": subject_hint or branch,
            "message": "수학 분기는 아직 구현되지 않았습니다 (국어/사회/과학/영어만 지원)",
        }
        result["finger_detected"] = finger_detected
        return result

    def ocr_result_for(b):
        return ocr_result_english if b == "영어" else ocr_result_guksagwa

    print(f"4. Gemini 2차 호출 ({branch})...")
    t_explain = time.perf_counter()
    explanation = _explainer_for(branch)(ocr_result_for(branch), {"과목": subject_hint},
                                          **common_kwargs)

    mismatch = explanation.get("subject_mismatch")
    if mismatch:
        suggested_branch = BRANCH_OF.get(mismatch, "국사과")
        if suggested_branch == "수학" or suggested_branch == branch:
            suggested_branch = "국사과"
        print(f"경고: subject_mismatch 반환됨 (지정={branch}, 제안={mismatch}) "
              f"-> {suggested_branch}로 1회 재호출")
        branch = suggested_branch
        explanation = _explainer_for(branch)(ocr_result_for(branch), {"과목": subject_hint},
                                              **common_kwargs)
        mismatch2 = explanation.get("subject_mismatch")
        if mismatch2:
            print(f"경고: 재호출도 subject_mismatch 반환됨 (제안={mismatch2}) "
                  "-> 국사과로 강제 진행 (재호출은 하지 않음, 무한루프 방지)")
            branch = "국사과"

    print(f"   ({time.perf_counter() - t_explain:.2f}초)")

    # 자가 검증: Gemini가 읽었다고 답한 문항 번호가 question_locator가 짚은 번호와 다르면
    # 옆 문제를 섞어 읽었을 가능성 - 응답은 그대로 반환하되 로그에 남긴다.
    reported_number = explanation.get("question_number")
    if reported_number is not None and reported_number != locate_result.question_number:
        print(f"WARNING: Gemini가 보고한 question_number({reported_number})가 "
              f"question_locator 결과({locate_result.question_number})와 다름 - 오독 의심")

    # category는 이미 "대분류 > 중분류" 형태이므로 있으면 그대로 쓰고, 없으면 과목명만.
    problem_type = category or subject_hint or ""

    if branch == "영어":
        options_out = explanation.get("options", [])
        result = {
            "status": "success",
            "type": "english",
            "subject": subject_hint or branch,
            "problem_type": problem_type,
            "passage": explanation.get("passage", {"text": "", "tokens": []}),
            "options": options_out,
            "translation": explanation.get("translation", {"passage": "", "options": []}),
            # 내부 explanation_text -> 외부 API 계약 필드 explanation으로 매핑 (국사과 분기와 동일한 이유)
            "explanation": explanation.get("explanation_text", ""),
            "answer": normalize_answer(explanation.get("answer"), options_out),
        }
    else:
        result = {
            "status": "success",
            "type": "guksagwa",
            "subject": subject_hint or branch,
            "problem_type": problem_type,
            "problem_text": locate_result.query_text,
            # 내부 explanation_text -> 외부 API 계약 필드 explanation으로 매핑
            # (explainer 반환 dict에는 explanation 키가 없음 - explanation_text만 있음.
            # 이 "explanation"은 run_pipeline() 응답의 필드명이라 프론트 계약상 이름을 유지함).
            "explanation": explanation.get("explanation_text", ""),
            "answer": normalize_answer(explanation.get("answer")),
        }

    result["finger_detected"] = finger_detected
    # v2는 자르지 않고 항상 marked_image(전체 페이지+박스)를 2차 호출에 붙이므로, v1의
    # "삽화가 있을 때만 첨부" 개념 자체가 없어졌다. has_illustration/illustration_bbox/
    # illustration(썸네일)은 이제 아무도 계산하지 않으므로 항상 비워서 내려보낸다.
    result["illustration_attached"] = True
    result["has_illustration"] = False
    result["illustration_bbox"] = None
    result["illustration"] = None

    result["branch"] = branch
    result["subject_hint"] = subject_hint
    result["agreement"] = agreement
    result["guard"] = guard
    result["fallback_level"] = locate_result.fallback_level
    result["locate_confidence"] = locate_result.locate_confidence
    result["anchor_recovered"] = locate_result.anchor_recovered
    result["similar_questions"] = similar_questions
    result["below_threshold"] = below_threshold

    return result


if __name__ == "__main__":
    import sys

    if len(sys.argv) not in (2, 4):
        print("사용법: python pipeline.py <이미지경로>            (손끝 좌표 자동 인식)")
        print("       python pipeline.py <이미지경로> <x> <y>    (좌표 직접 지정)")
        sys.exit(1)

    image_path = sys.argv[1]

    if len(sys.argv) == 4:
        x, y = int(sys.argv[2]), int(sys.argv[3])
    else:
        img = cv2.imread(image_path)
        if img is None:
            print(f"이미지를 읽을 수 없음: {image_path}")
            sys.exit(1)
        tip, tip_msg = find_finger_tip(img)
        if tip is None:
            print(f"손끝을 못 찾음: {tip_msg} (좌표를 직접 지정해주세요)")
            sys.exit(1)
        x, y = tip["x"], tip["y"]
        print(f"손끝 좌표 자동 인식(원본 기준 - 내부에서 리사이즈본으로 재검출됨): ({x}, {y})")

    final_result = run_pipeline(image_path, x, y)
    print(json.dumps(final_result, ensure_ascii=False, indent=2))
