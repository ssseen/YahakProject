"""
Gemini 1차 호출(problem_extractor.py)을 EasyOCR로 대체하는 실험용 모듈.

problem_extractor.extract_problem_info()와 반환 형태를 최대한 맞췄지만, EasyOCR은
텍스트만 읽을 뿐 이미지를 "이해"하지 못하므로 아래 세 가지는 채우지 못한다 (항상
고정값으로 채워짐 - 실험 목적상 이 한계를 명확히 표시해둔다):

  - subject: 항상 None (과목 판단은 이미지를 보고 하는 추론이라 OCR로는 불가능)
  - has_illustration / illustration_bbox: 항상 False / None (표·그래프 유무 판단도
    이미지 이해가 필요해서 OCR로는 불가능)

classify_problem()은 subject가 None이면 Pinecone 호출 자체를 생략하므로, 이 모듈만
단독으로 쓰면 항상 미분류로 빠진다 - 지금은 "OCR 텍스트 추출 자체의 속도/정확도"만
Gemini 1차와 비교하기 위한 실험용이고, subject를 채우는 문제는 별도로 풀어야 한다.
"""
import re
import time

import easyocr

_READER = None


def _get_reader():
    """easyocr.Reader는 생성 자체(모델 로딩)가 무거워서 최초 1회만 만들고 재사용한다."""
    global _READER
    if _READER is None:
        _READER = easyocr.Reader(["ko", "en"], gpu=False)
    return _READER


def _lines_from_boxes(results):
    """
    easyocr.readtext()가 반환하는 (bbox, text, confidence) 리스트를 읽는 순서(위->아래,
    같은 줄이면 왼쪽->오른쪽)로 정렬해 줄 단위 텍스트 리스트로 만든다.

    bbox는 4개 꼭짓점 좌표 [[x1,y1],[x2,y2],[x3,y3],[x4,y4]] (좌상단부터 시계방향) -
    좌상단 y좌표로 줄을, 같은 줄 안에서는 좌상단 x좌표로 순서를 정한다. "같은 줄"인지는
    y좌표 차이가 그 글자 높이의 절반 이내인지로 대략 판단한다(완벽한 레이아웃 분석은
    아니고 휴리스틱).
    """
    items = []
    for bbox, text, conf in results:
        x1, y1 = bbox[0]
        _, y4 = bbox[3]
        height = abs(y4 - y1) or 1
        items.append((y1, height, x1, text))

    items.sort(key=lambda it: (it[0], it[2]))

    lines = []
    current_line = []
    current_y = None
    current_h = None
    for y1, height, x1, text in items:
        if current_y is None or abs(y1 - current_y) <= current_h / 2:
            current_line.append((x1, text))
            current_y = y1 if current_y is None else current_y
            current_h = height if current_h is None else max(current_h, height)
        else:
            lines.append(" ".join(t for _, t in sorted(current_line)))
            current_line = [(x1, text)]
            current_y = y1
            current_h = height
    if current_line:
        lines.append(" ".join(t for _, t in sorted(current_line)))

    return lines


_OPTION_MARKER = re.compile(r"[①②③④⑤]")


def _split_passage_and_options(full_text):
    """
    ①②③④⑤ 마커를 기준으로 지문(passage_text)과 보기(options)를 분리한다.
    마커가 하나도 없으면(보기가 없는 문제 등) 전체를 passage_text로, options는 빈 리스트로.
    """
    match = _OPTION_MARKER.search(full_text)
    if not match:
        return full_text.strip(), []

    passage_text = full_text[: match.start()].strip()
    options_text = full_text[match.start():]

    markers = list(_OPTION_MARKER.finditer(options_text))
    options = []
    for i, m in enumerate(markers):
        start = m.end()
        end = markers[i + 1].start() if i + 1 < len(markers) else len(options_text)
        options.append({"no": i + 1, "text": options_text[start:end].strip()})

    return passage_text, options


def extract_problem_info_ocr(cropped_img):
    """
    problem_extractor.extract_problem_info()의 EasyOCR 버전.

    반환: {"subject": None, "ocr_text": str, "passage_text": str,
           "options": [{"no": int, "text": str}, ...], "keywords": [],
           "has_illustration": False, "illustration_bbox": None,
           "ocr_ms": float}
    ocr_ms는 순수 OCR 추론 시간(모델 로딩 제외) - Gemini 1차와 속도 비교용으로 추가한
    필드라 problem_extractor 쪽 반환 형태에는 없다.
    """
    reader = _get_reader()

    t0 = time.perf_counter()
    results = reader.readtext(cropped_img)
    ocr_ms = (time.perf_counter() - t0) * 1000

    lines = _lines_from_boxes(results)
    full_text = "\n".join(lines)
    passage_text, options = _split_passage_and_options(full_text)

    return {
        "subject": None,
        "ocr_text": full_text,
        "passage_text": passage_text,
        "options": options,
        "keywords": [],
        "has_illustration": False,
        "illustration_bbox": None,
        "ocr_ms": ocr_ms,
    }
