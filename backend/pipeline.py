"""
국어/사회/과학(국사과)/영어/수학 해설 파이프라인 - 엔드투엔드 오케스트레이션. v2.

  1) 이미지를 장축 1960px로 리사이즈 (Clova 권장 해상도, 이후 모든 좌표의 공통 기준)
  2) 리사이즈된 이미지에서 손끝을 다시 검출 (find_finger_tip) - main.py가 넘겨준 x,y는
     원본 이미지 좌표라 그대로 못 쓴다. 배율 변환 수식을 쓰는 대신, 이미 리사이즈된
     이미지에서 다시 검출해서 애초에 좌표계를 하나로 맞춘다 (변환 버그 여지 자체를 제거).
  3) Clova OCR 호출 -> 줄 목록(app.clova_client.to_lines)
  4) question_locator로 손끝이 가리키는 문항 특정 (번호 앵커 + 밴드, 자르지 않고 표시만)
  5) Pinecone 무필터 검색 1회 (top_k=30) -> 같은 결과를 과목 판정과 유사문제 선별에 나눠 씀
  6) subject_router로 과목(영어/수학/국사과) 판정
  7) 국어/사회/과학이면 explain_guksagwa로, 영어면 explain_english로, 수학이면 explain_math로 Gemini 2차 호출
     (v2의 유일한 LLM 호출)
  8) 과목 자가검증(subject_mismatch) 처리 + 문항번호 자가검증 로그
  9) 최종 JSON 조립

Gemini 1차 호출은 v2에서 완전히 제거됐다 (problem_extractor.py는 backend/experiments/로
이동 - EasyOCR 비교 실험의 비교 대상으로 계속 쓰이므로 삭제하지 않음, pipeline.py에서는
더 이상 import하지 않는다).
"""
import hashlib
import json
import re
import threading
import time
from collections import OrderedDict

import cv2
import numpy as np
from dotenv import load_dotenv
from pinecone import Pinecone
import os

from vision_processor import find_finger_tip, augment_box_with_ink
from app.clova_client import resize_for_ocr, call_clova, to_lines, rotate_image_bytes, ClovaError
from app.question_locator import locate_question, single_question_point, LocateError
from app.orientation import detect_rotation, rotate_response, rotate_point, rotate_image, upright_size
from app.deskew import (
    estimate_skew_ocr, deskew_matrix, warp_response, warp_point, warp_image, MIN_SKEW_DEG, MAX_SKEW_DEG,
)
from app.subject_router import decide_branch, select_similar, BRANCH_OF
try:
    from type_classifier import classify_type
except ImportError:
    classify_type = None
from guksagwa_explainer import explain_guksagwa
from english_explainer import explain_english
from math_explainer import explain_math
from answer_utils import normalize_answer

load_dotenv()

_PINECONE_INDEX_NAME = "geondi-questions"
_PINECONE_NAMESPACE = "questions"
_PINECONE_TOP_K = 30
_BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")

_OPTION_MARKERS = "①②③④"


def _marker_pattern(n: int):
    """n번 보기 마커 패턴 - 원문자(①~④) 또는, Clova가 원문자를 못 읽고 맨 숫자로
    반환한 경우를 대비해 공백으로 둘러싸인 숫자 n도 같이 허용한다 (실제로 ④가
    "4"로 인식돼 보기 3번 텍스트 뒤에 붙어버리는 사례가 있었음).
    n이 지원 범위(1~4번, _OPTION_MARKERS 길이)를 벗어나면 None을 반환한다 -
    호출부가 이를 "더 이상 다음 마커 없음"으로 보고 루프를 멈춰야 한다."""
    if n < 1 or n > len(_OPTION_MARKERS):
        return None
    circled = _OPTION_MARKERS[n - 1]
    return re.compile(rf"{re.escape(circled)}|(?<=\s){n}(?!\d)(?=\s)")

_RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")

# 손끝 없는 사진의 OCR 결과 캐시 (2026-10-26).
# 촬영 직후 검사(check_without_finger)와 제출 후 본 처리(run_pipeline)에 같은 사진이 두 번
# 들어오는데, 손끝이 없으면 둘 다 Clova OCR + 방향/기울기 보정을 해서 OCR이 2번 돌았다.
# 첫 번째 결과를 사진 해시로 잠깐 보관했다가 두 번째에서 꺼내 쓴다. 서버 메모리라
# 다른 인스턴스로 요청이 가거나 TTL이 지나면 못 찾고, 그때는 예전처럼 OCR을 다시 한다.
_OCR_CACHE = OrderedDict()
_OCR_CACHE_LOCK = threading.Lock()
_OCR_CACHE_MAX = 8          # 항목당 1960px 이미지(~9MB)를 들고 있으므로 작게 유지
_OCR_CACHE_TTL_SEC = 600    # 사진 찍고 음성 질문까지 넉넉히 10분


def _image_key(image_path):
    with open(image_path, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()


def _ocr_cache_put(key, value):
    with _OCR_CACHE_LOCK:
        _OCR_CACHE[key] = (time.time(), value)
        _OCR_CACHE.move_to_end(key)
        while len(_OCR_CACHE) > _OCR_CACHE_MAX:
            _OCR_CACHE.popitem(last=False)


def _ocr_cache_pop(key):
    with _OCR_CACHE_LOCK:
        item = _OCR_CACHE.pop(key, None)
    if item is None or time.time() - item[0] > _OCR_CACHE_TTL_SEC:
        return None
    return item[1]


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
    Pinecone 무필터 검색 1회 (top_k=30). 이 결과를 subject_router.decide_branch(과목 판정)와
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


def warmup_pinecone():
    """
    Pinecone 클라이언트 생성 + 연결을 미리 해둔다 (2026-10-26). 프로세스의 첫 검색만 연결
    준비 때문에 4초 안팎 걸리고 이후는 1~2초였다(속도측정 105/34/22/375.jpg) - 서버 기동 시
    한 번 불러서 첫 사용자가 그 시간을 겪지 않게 한다. 실패해도 로그만 남긴다(첫 요청 때 다시 연결됨).
    """
    t0 = time.perf_counter()
    try:
        _search_unfiltered("warmup")
        print(f"[Pinecone] 미리 연결 완료 ({time.perf_counter() - t0:.1f}초)")
    except Exception as e:
        print(f"[Pinecone] 미리 연결 실패 (첫 요청 때 다시 시도): {e!r}")


def _split_passage_and_options(text):
    """
    question_locator가 만든 query_text(범위 지시문 + 지문/발문 + 보기가 한 문자열로 합쳐진 것)를
    영어 분기 explainer가 요구하는 passage_text/options 형태로 다시 나눈다. ①이 처음 나오는
    지점을 기준으로 그 앞을 지문, 그 뒤를 보기로 본다. 국사과/수학 분기는 이 분리가 필요 없어
    ocr_text(=query_text 그대로)만 쓴다 (branch == "영어"일 때만 호출됨).
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
        pattern = _marker_pattern(n)
        if pattern is None:
            break
        m = pattern.search(remainder, positions[-1] + 1)
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
    """
    Pinecone hit -> 프론트에 내려줄 유사문제 형태로 변환.

    2026-09-11 파인콘 데이터 담당자가 인덱스를 재업로드하면서 스키마가 바뀜
    (HANDOFF.md 6번 섹션 "대기 중" 항목이 이걸로 해결됨):
      - `text`(지문+보기가 한 덩어리로 뭉친 문자열)는 그대로 유지되고,
        `question`(지문만)/`choices`(보기만)가 새로 추가됨 - "유사문제 풀어보기"
        화면에서 보기를 따로따로 보여주려면 이제 text를 직접 파싱할 필요 없이
        이 두 필드를 쓰면 됨.
      - `has_image`/`image_path`가 새로 추가됨. `has_image`는 Pinecone엔 문자열
        "1"/"0"으로 들어있어서(메타데이터가 문자열만 지원하는 제약으로 추정) 여기서
        boolean으로 변환해서 내려준다. `image_path`는 이미지 없으면 빈 문자열로
        들어오므로 그대로 통과시킨다(프론트에서 falsy 체크 가능).
    """
    out = []
    for m in matches:
        fields = getattr(m, "fields", None) or {}
        out.append({
            "id": getattr(m, "id", None),
            "score": getattr(m, "score", None),
            "text": fields.get("text", ""),
            "question": fields.get("question", ""),
            "choices": fields.get("choices", ""),
            "answer": fields.get("answer"),
            "explanation": fields.get("explanation", ""),
            "has_image": fields.get("has_image") == "1",
            "image_path": fields.get("image_path", ""),
            "year": fields.get("year"),
            "exam_round": fields.get("exam_round"),
            "question_number": fields.get("question_number"),
        })
    return out


_RETAKE_MESSAGES = {
    "no_finger": "손끝이 검출되지 않았습니다.\n다시 찍어주세요",
    "no_text": "글자를 읽지 못했어요.\n다시 찍어주세요",
    "location_failed": "문제 위치를 찾지 못했어요.\n다시 찍어주세요",
    "rotation_misdetected": "사진을 다시 읽지 못했어요.\n다시 찍어주세요",
}
_RETAKE_MESSAGE_DEFAULT = "사진을 인식하지 못했어요.\n다시 찍어주세요"


def _retake_response(reason, blur_score=None, brightness=None):
    """
    retake 응답 스키마를 하나로 통일한다. 해당 없는 값은 null.

    실사용 중 발견(2026-09-15) - "message" 필드가 아예 없어서, 프론트
    (photo-processing.js)가 `errorMessage = data.message`를 그대로 화면에 찍을 때
    문자 그대로 "undefined"가 떴다(사진 제출 직후 손끝 재검출 실패 등으로 이 경로를
    자주 탐). vision_processor.py의 품질 검사(blur/brightness) retake는 자체적으로
    message를 채워 보내므로 이 버그가 없었다 - pipeline.py 내부에서 만드는 retake만
    빠져 있었음.
    """
    return {
        "status": "retake",
        "reason": reason,
        "message": _RETAKE_MESSAGES.get(reason, _RETAKE_MESSAGE_DEFAULT),
        "blur_score": blur_score,
        "brightness": brightness,
        "skew_deg": None,  # vision_processor.py를 건드리지 않는 한 계산할 수 없음
        "text_object_count": None,  # 위와 동일
    }


def _explainer_for(branch):
    if branch == "영어":
        return explain_english
    if branch == "수학":
        return explain_math
    return explain_guksagwa


def run_pipeline(image_path, x, y, stt_text=None, user_question="이 문제 좀 알려줘",
                  classification_override=None, save_path=None, user_level=None):
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

    반환 (해설 응답 명세서 - 국사과/영어/수학 분기 참고):
      국사과 성공 시 {"status": "success", "type": "guksagwa", "subject": str,
                    "problem_type": str, "problem_text": str, "explanation": str,
                    "answer": {"number": int|None, "text": str}, ...}
      영어 성공 시   {"status": "success", "type": "english", "subject": str,
                    "problem_type": str, "passage": {...}, "options": [...],
                    "translation": {...}, "explanation": str,
                    "answer": {"number": int|None, "text": str}, ...}
      수학 성공 시   {"status": "success", "type": "math", "subject": str,
                    "problem_type": str, "steps": [{"step_number": int, "text": str}, ...],
                    "explanation": str, "answer": {"number": int|None, "text": str},
                    "diagram_path": str|None, ...}
      미지원 과목    {"status": "unsupported_subject", "subject": str, "message": str}
      재촬영 요청    {"status": "retake", "reason": str, "message": str, "blur_score",
                    "brightness", "skew_deg", "text_object_count"} (해당 없는 값은 null)
      오류 시        {"status": "error", "message": str}  (HTTP 500이 아니라 200으로 나감 -
                    main.py가 이 함수가 반환한 dict를 그대로 JSON 응답으로 돌려주기 때문에,
                    여기서 예외를 밖으로 던지지만 않으면 자동으로 200이 된다)

    성공 응답에는 공통으로 finger_detected, illustration_attached(marked_image 첨부 여부),
    branch, subject_hint, agreement, guard, fallback_level, locate_confidence,
    anchor_recovered, similar_questions, below_threshold가 붙는다.
    """
    pipeline_start = time.perf_counter()
    # 단계별 소요 시간(초) - 응답의 "timings"로도 내려보낸다 (속도 측정용, 2026-10-26)
    timings = {}

    try:
        result = _run_pipeline_inner(image_path, x, y, stt_text, user_question,
                                      classification_override, user_level, timings)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"오류: 파이프라인 처리 중 예외 발생: {e!r}")
        result = {"status": "error", "message": str(e)}

    timings["pipeline_total"] = round(time.perf_counter() - pipeline_start, 3)
    print(f"전체 소요 시간: {timings['pipeline_total']:.2f}초")
    print(f"   [시간] {timings}")
    result["timings"] = timings

    # save_path를 안 줘도(main.py는 안 줌) 매 요청 결과를 backend/results/에 자동 저장한다.
    # 그전엔 API로 들어온 요청은 응답만 하고 사라져서 나중에 다시 볼 방법이 없었다.
    t_save = time.perf_counter()
    auto_path = os.path.join(_RESULTS_DIR, f"{time.strftime('%Y%m%d_%H%M%S')}_{os.getpid()}.json")
    os.makedirs(_RESULTS_DIR, exist_ok=True)
    with open(auto_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    timings["save_json"] = round(time.perf_counter() - t_save, 3)
    print(f"결과 저장됨: {auto_path}")

    if save_path:
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

    return result


def _lap(timings, key, t0):
    """t0부터 지금까지 걸린 시간을 timings[key]에 더한다 (같은 단계가 여러 번이면 합산)."""
    timings[key] = round(timings.get(key, 0) + time.perf_counter() - t0, 3)


def _ocr_upright(resized_bytes, resized_img, page_w, page_h, fx, fy, timings):
    """
    Clova OCR + 좌표계 보정(Clova 크기 불일치 재시도, 방향 세우기, 기울기 펴기)을 한다.
    손끝 좌표(fx, fy)도 같은 변환을 받는다 - 손끝이 없으면(None) 좌표 변환만 건너뛴다.
    timings에 clova(호출 시간 합), clova_calls(호출 횟수), upright(보정 시간)를 기록한다.

    반환: (실패 응답, None) 또는 (None, (ocr_data, resized_img, page_w, page_h, fx, fy))
    """
    print("1. Clova OCR 호출...")
    t_ocr = time.perf_counter()
    timings["clova_calls"] = timings.get("clova_calls", 0) + 1
    try:
        clova_response = call_clova(resized_bytes)
    except ClovaError as e:
        return {"status": "error", "message": f"OCR 호출 실패: {e}"}, None
    _lap(timings, "clova", t_ocr)
    ocr_data = to_lines(clova_response)
    print(f"   줄 {len(ocr_data['lines'])}개, page_conf_min={ocr_data['page_conf_min']} "
          f"({time.perf_counter() - t_ocr:.2f}초)")

    if not ocr_data["lines"]:
        return _retake_response(reason="no_text"), None

    # Clova가 우리가 보낸 사진과 다른 크기(가로/세로 뒤바뀜)로 응답한 경우 - 사진을 내부에서
    # 돌려 읽은 것이라 좌표계가 우리 사진과 안 맞는다(실측 35.jpg, 100장 중 1장). 이때만
    # 예전처럼 사진을 90도 돌려 Clova를 1회 다시 부른다.
    clova_size = (ocr_data["page_w"], ocr_data["page_h"])
    if None not in clova_size and clova_size != (page_w, page_h):
        print(f"경고: Clova 응답 크기 {clova_size}가 보낸 사진 {(page_w, page_h)}와 다름 "
              "- 90도 회전 후 재시도")
        try:
            rot_bytes, rot_w, rot_h = rotate_image_bytes(resized_bytes)
            t_retry = time.perf_counter()
            timings["clova_calls"] += 1
            clova_response = call_clova(rot_bytes)
            _lap(timings, "clova", t_retry)
        except ClovaError as e:
            return {"status": "error", "message": f"OCR 재시도 실패: {e}"}, None
        retry_data = to_lines(clova_response)
        if not retry_data["lines"] or (retry_data["page_w"], retry_data["page_h"]) != (rot_w, rot_h):
            print("   -> 회전 재시도도 좌표계 불일치 - 재촬영 필요")
            return _retake_response(reason="rotation_misdetected"), None
        # Image.rotate(90, expand=True) 방향(반시계) 기준 좌표 변환: 회전 전
        # 페이지 폭(page_w) 기준으로 새 x = 기존 y, 새 y = (page_w - 1) - 기존 x.
        if fx is not None:
            fx, fy = fy, page_w - 1 - fx
        page_w, page_h = rot_w, rot_h
        resized_img = cv2.imdecode(np.frombuffer(rot_bytes, np.uint8), cv2.IMREAD_COLOR)
        ocr_data = retry_data

    # 종이를 옆으로/거꾸로 놓고 찍은 사진은 Clova가 글자는 제대로 읽지만 좌표 축이 누워
    # 있다. 단어 좌표로 글 읽는 방향을 판정해 줄·손끝·이미지를 똑바로 세운다 (Clova 재호출
    # 없음, app/orientation.py 참고). 이후 단계(문항 특정, 빨간 박스, Gemini)는 전부
    # 세운 좌표계에서 동작한다.
    t_upright = time.perf_counter()
    angle, votes = detect_rotation(clova_response)
    if angle:
        print(f"   페이지가 {angle}도 누워 있음 (득표 {votes}) - 똑바로 세움")
        clova_response = rotate_response(clova_response, angle, page_w, page_h)
        if fx is not None:
            fx, fy = rotate_point(fx, fy, angle, page_w, page_h)
        resized_img = rotate_image(resized_img, angle)
        page_w, page_h = upright_size(angle, page_w, page_h)

    # 살짝(1~20도) 기운 사진은 줄 박스가 위아래로 부풀어 옆 줄·옆 문항과 겹친다. OCR 단어
    # 좌표로 줄 기울기를 재서 사진(cv2.warpAffine)과 단어 꼭짓점·손끝을 같은 행렬로 편 뒤
    # 줄을 다시 묶는다 (Clova 재호출 없음, app/deskew.py 참고). 415장을 인위적으로 15도
    # 기울인 실험에서 문항 특정 89.0% -> 96.8%.
    skew = estimate_skew_ocr(clova_response)
    if skew is not None and MIN_SKEW_DEG <= abs(skew) <= MAX_SKEW_DEG:
        print(f"   페이지가 {skew:.1f}도 기울어 있음 - 수평으로 폄")
        M, nw, nh = deskew_matrix(skew, page_w, page_h)
        clova_response = warp_response(clova_response, M, nw, nh)
        if fx is not None:
            fx, fy = warp_point(fx, fy, M)
        resized_img = warp_image(resized_img, M, nw, nh)
        page_w, page_h = nw, nh

    # 방향·기울기 보정이 적용됐을 수 있으므로 보정된 단어 좌표로 줄을 다시 묶는다
    # (보정이 없었으면 처음과 같은 결과).
    ocr_data = to_lines(clova_response)
    _lap(timings, "upright", t_upright)

    return None, (ocr_data, resized_img, page_w, page_h, fx, fy)


def check_without_finger(image_path, timings=None):
    """
    사진 촬영 직후 검사(checkOnly)에서 손끝이 안 잡혔을 때 부른다 (2026-10-21).
    사진에 문제가 하나뿐이면 None(그대로 진행), 아니면 다시 찍기/에러 응답을 돌려준다 -
    음성 질문까지 받은 뒤에야 다시 찍으라고 하지 않도록 촬영 단계에서 미리 판단한다.
    통과하면 OCR 결과를 _OCR_CACHE에 보관해 run_pipeline이 재사용한다.
    timings(dict)를 주면 단계별 소요 시간을 채운다.
    """
    timings = {} if timings is None else timings
    t_resize = time.perf_counter()
    try:
        resized_bytes, page_w, page_h = resize_for_ocr(image_path)
    except Exception as e:
        return {"status": "error", "message": f"이미지를 읽을 수 없음: {e}"}
    resized_img = cv2.imdecode(np.frombuffer(resized_bytes, np.uint8), cv2.IMREAD_COLOR)
    if resized_img is None:
        return {"status": "error", "message": "이미지 디코딩 실패"}
    _lap(timings, "resize", t_resize)

    fail, ctx = _ocr_upright(resized_bytes, resized_img, page_w, page_h, None, None, timings)
    if fail is not None:
        return fail
    ocr_data, resized_img, page_w, page_h, _, _ = ctx
    t_single = time.perf_counter()
    single = single_question_point(ocr_data["lines"], page_h)
    _lap(timings, "single_question", t_single)
    print(f"   손끝 없음 - 문제 하나뿐: {single[0] if single else '아님'}")
    if single is None:
        return _retake_response(reason="no_finger")
    # 제출 후 run_pipeline이 같은 사진으로 OCR을 다시 하지 않도록 보관
    _ocr_cache_put(_image_key(image_path), (ocr_data, resized_img, page_w, page_h, single))
    return None


def _run_pipeline_inner(image_path, x, y, stt_text, user_question, classification_override, user_level=None,
                        timings=None):
    timings = {} if timings is None else timings
    finger_detected = x is not None and y is not None
    fx, fy = None, None
    single = None

    # 손끝 없는 사진은 촬영 검사(check_without_finger) 때 이미 OCR을 했으므로 그 결과를 꺼내 쓴다
    cached = None if finger_detected else _ocr_cache_pop(_image_key(image_path))
    if not finger_detected:
        timings["ocr_cache_hit"] = cached is not None
    if cached is not None:
        ocr_data, resized_img, page_w, page_h, single = cached
        print(f"0~1. 촬영 검사 때 한 리사이즈+OCR 결과 재사용 - Clova 재호출 없음 "
              f"(줄 {len(ocr_data['lines'])}개)")
    else:
        t_resize = time.perf_counter()
        try:
            resized_bytes, page_w, page_h = resize_for_ocr(image_path)
        except Exception as e:
            return {"status": "error", "message": f"이미지를 읽을 수 없음: {e}"}

        resized_img = cv2.imdecode(np.frombuffer(resized_bytes, np.uint8), cv2.IMREAD_COLOR)
        if resized_img is None:
            return {"status": "error", "message": "이미지 디코딩 실패"}
        _lap(timings, "resize", t_resize)
        print(f"0. 이미지 리사이즈 (장축 1960px, {page_w}x{page_h}) 완료 "
              f"({timings['resize']:.2f}초)")

        if finger_detected:
            t_finger = time.perf_counter()
            tip, tip_msg = find_finger_tip(resized_img)
            _lap(timings, "finger_redetect", t_finger)
            if tip is not None:
                fx, fy = tip["x"], tip["y"]
            else:
                print(f"경고: 원본에서는 손끝을 찾았으나 리사이즈본에서는 재검출 실패({tip_msg}) "
                      "- 손끝 없음으로 처리")
                finger_detected = False

        fail, ctx = _ocr_upright(resized_bytes, resized_img, page_w, page_h, fx, fy, timings)
        if fail is not None:
            return fail
        ocr_data, resized_img, page_w, page_h, fx, fy = ctx

    # 손끝이 안 잡혔으면: 사진에 문제가 하나뿐이면 그 문제로 진행, 여러 개면 다시 찍기 (2026-10-21)
    if not finger_detected:
        if single is None:
            t_single = time.perf_counter()
            single = single_question_point(ocr_data["lines"], page_h)
            _lap(timings, "single_question", t_single)
        if single is None:
            print("   손끝 없음 + 문제가 여러 개(또는 못 찾음) - 다시 찍기")
            return _retake_response(reason="no_finger")
        fx, fy = single[1]
        print(f"   손끝 없음 - 문제가 {single[0]}번 하나뿐이라 그 문제로 진행")

    print("2. 문항 특정 (question_locator)...")
    t_locate = time.perf_counter()
    try:
        locate_result = locate_question(ocr_data["lines"], (fx, fy), page_h)
    except LocateError as e:
        _lap(timings, "locate", t_locate)
        print(f"경고: 문항 특정 실패: {e}")
        return _retake_response(reason="location_failed")
    _lap(timings, "locate", t_locate)
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

    print("3. Pinecone 검색 (무필터, top_k=30)...")
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
        branch_result = decide_branch(matches[:10], locate_result.query_text)
        branch = branch_result.branch
        subject_hint = branch_result.subject_hint
        agreement, vote_count, guard = (branch_result.agreement, branch_result.vote_count,
                                         branch_result.guard)
    print(f"   -> branch={branch}, subject_hint={subject_hint}, agreement={agreement}, "
          f"guard={guard} ({time.perf_counter() - t_search:.2f}초)")
    # [로그] 필수 필드
    print(f"   [로그] agreement={agreement} vote_count={vote_count} guard={guard}")

    similar_questions = _format_similar_questions(select_similar(matches, branch, exclude_id=None, user_level=user_level))
    below_threshold = not similar_questions
    category = _category_hint_for_branch(matches[:10], branch)
    _lap(timings, "pinecone", t_search)

    t_type = time.perf_counter()
    type_info = None
    if classify_type is not None and os.getenv("ENABLE_TYPE_CLASSIFIER") == "1" and guard is None and subject_hint:
        try:
            tr = classify_type(_get_pinecone_index(), locate_result.query_text, subject_hint, user_level)
            if tr.category_large or tr.category_mid:
                type_info = {"categoryLarge": tr.category_large,
                             "categoryMid": tr.category_mid, "sameLevel": tr.same_level}
        except Exception as e:
            print(f"경고: 유형 분류 실패, 기존 category 사용: {e!r}")
            
            
    _lap(timings, "type_classifier", t_type)

    t_box = time.perf_counter()
    box = locate_result.box
    # 화면에 그리는 박스만, 그림·표(글자 없는 영역)를 추가로 포함하도록 보강한다.
    # query_text/low_conf_lines 등 텍스트 기반 판단에는 원래 박스(box)를 그대로 쓴다
    # - 보강은 "눈으로 보기 좋게"가 목적이지 검색/판정용 텍스트 범위를 바꾸는 게 아니다.
    marked_box = augment_box_with_ink(resized_img, box, locate_result.col_x_range,
                                       locate_result.band_y_range)
    marked_img = resized_img.copy()
    cv2.rectangle(marked_img, (marked_box[0], marked_box[1]), (marked_box[2], marked_box[3]),
                  (0, 0, 255), 4)
    _lap(timings, "box", t_box)

    # _split_passage_and_options는 영어 분기 전용 파싱이라 branch가 "영어"일 때만 돌린다
    # (수학/국사과 분기가 이 결과를 쓰지 않는데도 항상 호출되고 있었던 게, 보기 개수/형식이
    # 특이한 수학 문제에서 IndexError를 내는 원인이었다 - 2026-09-26 발견).
    ocr_result_guksagwa = {"ocr_text": locate_result.query_text, "keywords": []}
    if branch == "영어":
        passage, options_v2 = _split_passage_and_options(locate_result.query_text)
        ocr_result_english = {
            "ocr_text": locate_result.query_text,
            "passage_text": passage,
            "options": options_v2,
        }
    else:
        ocr_result_english = None

    reference = None
    if similar_questions:
        top = similar_questions[0]
        reference = {"answer": top.get("answer"), "explanation": top.get("explanation")}

    # 음성 질문은 transcript 하나로만 넘긴다 - explainer가 프롬프트 맨 끝에 한 번만 붙인다.
    common_kwargs = dict(
        marked_image=marked_img,
        user_question=None,
        subject_hint=subject_hint,
        category=category,
        transcript=stt_text or user_question,
        reference=reference,
    )

    def ocr_result_for(b):
        if b == "영어":
            return ocr_result_english
        return ocr_result_guksagwa

    print(f"4. Gemini 2차 호출 ({branch})...")
    t_explain = time.perf_counter()
    explanation = _explainer_for(branch)(ocr_result_for(branch), {"과목": subject_hint},
                                          **common_kwargs)
    gemini_calls = [explanation.get("gemini")]

    mismatch = explanation.get("subject_mismatch")
    if mismatch:
        suggested_branch = BRANCH_OF.get(mismatch, "국사과")
        if suggested_branch == "수학" or suggested_branch == branch:
            suggested_branch = "국사과"
        print(f"경고: subject_mismatch 반환됨 (지정={branch}, 제안={mismatch}) "
              f"-> {suggested_branch}로 1회 재호출")
        branch = suggested_branch
        # 재호출 브랜치가 "영어"로 바뀌는 경우를 대비해, 아직 안 만들어둔 ocr_result_english를
        # 이 시점에 만든다 (처음부터 branch == "영어"였으면 위에서 이미 만들어져 있음).
        if branch == "영어" and ocr_result_english is None:
            passage, options_v2 = _split_passage_and_options(locate_result.query_text)
            ocr_result_english = {
                "ocr_text": locate_result.query_text,
                "passage_text": passage,
                "options": options_v2,
            }
        explanation = _explainer_for(branch)(ocr_result_for(branch), {"과목": subject_hint},
                                              **common_kwargs)
        gemini_calls.append(explanation.get("gemini"))
        mismatch2 = explanation.get("subject_mismatch")
        if mismatch2:
            print(f"경고: 재호출도 subject_mismatch 반환됨 (제안={mismatch2}) "
                  "-> 국사과로 강제 진행 (재호출은 하지 않음, 무한루프 방지)")
            branch = "국사과"

    _lap(timings, "explain_total", t_explain)
    gemini_calls = [g for g in gemini_calls if g]
    timings["gemini_calls"] = gemini_calls
    timings["gemini"] = round(sum(g["seconds"] for g in gemini_calls), 3)
    print(f"   ({timings['explain_total']:.2f}초, Gemini API {timings['gemini']:.2f}초, "
          f"토큰 {[(g['prompt_tokens'], g['output_tokens'], g['thinking_tokens']) for g in gemini_calls]})")

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
    elif branch == "수학":
        _diagram_path = explanation.get("diagram_path")
        result = {
            "status": "success",
            "type": "math",
            "subject": subject_hint or branch,
            "problem_type": problem_type,
            "problem_text": explanation.get("problem_text") or locate_result.query_text,
            "steps": explanation.get("steps", []),
            "explanation": explanation.get("explanation_text", ""),
            "answer": normalize_answer(explanation.get("answer")),
            "diagram_path": _diagram_path,
            "explanationImage": f"{_BASE_URL}{_diagram_path}" if _diagram_path else None,
        }
    else:
        result = {
            "status": "success",
            "type": "guksagwa",
            "subject": subject_hint or branch,
            "problem_type": problem_type,
            "problem_text": explanation.get("problem_text") or locate_result.query_text,
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
    result["type_info"] = type_info

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