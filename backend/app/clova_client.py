"""
Clova OCR 호출 및 줄 정규화.

scripts/clova_probe.py로 확인한 실제 응답 구조를 따른다: images[0].fields[]에
boundingPoly.vertices(4점), inferText, inferConfidence, type, lineBreak가
있고, convertedImageInfo.width/height에 리사이즈 후 이미지 크기가 있다.

enableTableDetection은 끄기로 결정함(2026-08-25) — 표 형식 문제 몇 개만 영향받고
콘솔 도메인 토글까지 켜야 하는 번거로움 대비 이득이 적다고 판단. [[project-yahak-v2-pipeline]]
"""
import base64
import io
import os
import time
import uuid

import httpx
from PIL import Image, ImageOps

from app.question_locator import Line

_INVOKE_URL_ENV = "CLOVA_INVOKE_URL"
_SECRET_KEY_ENV = "CLOVA_SECRET_KEY"
_TIMEOUT_SEC = 30.0
_RETRY_GAP_SEC = 1.0  # 권장 호출 성능 1 tps 준수
_LONG_SIDE = 1960
_LOW_CONF_THRESHOLD = 0.7


class ClovaError(Exception):
    pass


def resize_for_ocr(image_path: str, long_side: int = _LONG_SIDE) -> tuple[bytes, int, int]:
    """
    이미지를 장축 long_side(기본 1960px)로 리사이즈해 JPEG 바이트로 반환한다.
    이미 그보다 작으면 원본 크기 그대로 인코딩만 다시 한다.

    exif_transpose를 먼저 적용한다 - 휴대폰 사진은 대부분 EXIF Orientation 태그로
    "회전해서 보여달라"고만 표시하고 실제 픽셀은 안 돌린 채로 저장한다. 이걸 안 하면
    사람 눈(과 EXIF를 읽는 뷰어)에는 똑바로 보이는 사진이, 여기서 읽은 픽셀 좌표
    기준으로는 옆으로 누워 나와서 손끝 재검출/Clova OCR/question_locator가 전부
    틀어진다 (실제로 이 버그로 문항 특정이 실패한 사례가 있었음).
    """
    img = ImageOps.exif_transpose(Image.open(image_path)).convert("RGB")
    w, h = img.size
    scale = long_side / max(w, h)
    if scale < 1:
        w, h = round(w * scale), round(h * scale)
        img = img.resize((w, h), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue(), w, h


def _post_once(invoke_url: str, secret_key: str, image_bytes: bytes) -> httpx.Response:
    body = {
        "version": "V2",
        "requestId": str(uuid.uuid4()),
        "timestamp": int(time.time() * 1000),
        "lang": "ko",
        "images": [{
            "format": "jpg",
            "name": "problem",
            "data": base64.b64encode(image_bytes).decode("ascii"),
        }],
        "enableTableDetection": False,
    }
    headers = {"Content-Type": "application/json", "X-OCR-SECRET": secret_key}
    return httpx.post(invoke_url, headers=headers, json=body, timeout=_TIMEOUT_SEC)


def call_clova(image_bytes: bytes) -> dict:
    """
    Clova General OCR V2를 호출한다. 네트워크 오류/5xx는 1초 간격을 두고 1회
    재시도하며, 그래도 실패하면 ClovaError를 던진다. 4xx는 재시도해도 같은
    결과이므로 즉시 ClovaError를 던진다.
    """
    invoke_url = os.getenv(_INVOKE_URL_ENV)
    secret_key = os.getenv(_SECRET_KEY_ENV)
    if not invoke_url or not secret_key:
        raise ClovaError(f"{_INVOKE_URL_ENV} 또는 {_SECRET_KEY_ENV}가 .env에 없음")

    last_error = None
    for attempt in range(2):
        try:
            resp = _post_once(invoke_url, secret_key, image_bytes)
        except httpx.HTTPError as e:
            last_error = f"요청 실패: {e!r}"
            if attempt == 0:
                time.sleep(_RETRY_GAP_SEC)
                continue
            raise ClovaError(last_error) from e

        if resp.status_code == 200:
            return resp.json()

        if 400 <= resp.status_code < 500:
            raise ClovaError(f"Clova 호출 실패 (HTTP {resp.status_code}): {resp.text[:500]}")

        last_error = f"Clova 호출 실패 (HTTP {resp.status_code}): {resp.text[:500]}"
        if attempt == 0:
            time.sleep(_RETRY_GAP_SEC)

    raise ClovaError(last_error)


def to_lines(response: dict) -> dict:
    """
    Clova 원본 응답 -> {"lines": [Line, ...], "page_w", "page_h",
    "page_conf_min", "low_conf_lines"}.

    lineBreak=True인 필드에서 줄을 끊어 fields를 줄 단위로 결합하고, 각 줄의
    boundingPoly는 그 줄에 속한 필드들의 bbox를 합친 값이다. low_conf_lines는
    줄 내 최저 inferConfidence가 0.7 미만인 줄의 인덱스 목록이다.
    """
    images = response.get("images") or []
    if not images:
        return {"lines": [], "page_w": None, "page_h": None,
                "page_conf_min": None, "low_conf_lines": []}

    image0 = images[0]
    conv = image0.get("convertedImageInfo") or {}
    page_w = conv.get("width")
    page_h = conv.get("height")
    fields = image0.get("fields") or []

    lines: list[Line] = []
    line_conf_mins: list[float] = []

    def _flush(texts, boxes, confs):
        x1 = min(b[0] for b in boxes)
        y1 = min(b[1] for b in boxes)
        x2 = max(b[2] for b in boxes)
        y2 = max(b[3] for b in boxes)
        lines.append(Line(" ".join(texts), (int(x1), int(y1), int(x2), int(y2))))
        confs_clean = [c for c in confs if c is not None]
        line_conf_mins.append(min(confs_clean) if confs_clean else None)

    cur_texts, cur_boxes, cur_confs = [], [], []
    for f in fields:
        verts = f["boundingPoly"]["vertices"]
        xs = [v["x"] for v in verts]
        ys = [v["y"] for v in verts]
        cur_texts.append(f.get("inferText", ""))
        cur_boxes.append((min(xs), min(ys), max(xs), max(ys)))
        cur_confs.append(f.get("inferConfidence"))
        if f.get("lineBreak"):
            _flush(cur_texts, cur_boxes, cur_confs)
            cur_texts, cur_boxes, cur_confs = [], [], []
    if cur_texts:
        _flush(cur_texts, cur_boxes, cur_confs)

    all_confs = [f.get("inferConfidence") for f in fields if f.get("inferConfidence") is not None]
    page_conf_min = min(all_confs) if all_confs else None

    low_conf_lines = [i for i, c in enumerate(line_conf_mins) if c is not None and c < _LOW_CONF_THRESHOLD]

    return {
        "lines": lines,
        "page_w": page_w,
        "page_h": page_h,
        "page_conf_min": page_conf_min,
        "low_conf_lines": low_conf_lines,
    }
