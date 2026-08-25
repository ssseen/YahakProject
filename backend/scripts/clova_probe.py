"""
CLOVA OCR General API 응답 구조 확인용 탐침 스크립트.

사용법: python scripts/clova_probe.py <image_path>

기존 파일(main.py, pipeline.py, classifier.py, vision_processor.py,
english_explainer.py 등)은 이 스크립트에서 import하지 않는다 — 완전히 독립된
탐침용 스크립트다.
"""
import base64
import io
import json
import os
import statistics
import sys
import time
import uuid

import httpx
from dotenv import load_dotenv
from PIL import Image

load_dotenv()

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "out")


def _resize_for_ocr(image_path: str, long_side: int = 1960) -> bytes:
    img = Image.open(image_path)
    img = img.convert("RGB")
    w, h = img.size
    scale = long_side / max(w, h)
    if scale < 1:
        img = img.resize((round(w * scale), round(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _call_clova(invoke_url: str, secret_key: str, image_bytes: bytes, enable_table: bool) -> tuple[int, dict | None, str]:
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
        "enableTableDetection": enable_table,
    }
    headers = {"Content-Type": "application/json", "X-OCR-SECRET": secret_key}
    resp = httpx.post(invoke_url, headers=headers, json=body, timeout=30.0)
    try:
        data = resp.json()
    except Exception:
        data = None
    return resp.status_code, data, resp.text


def _summarize(data: dict):
    print("--- 구조 요약 ---")
    if not isinstance(data, dict):
        print("응답이 dict가 아님:", type(data))
        return

    if "images" not in data:
        print("images 키 없음")
        return
    images = data["images"]
    if not images:
        print("images 배열이 비어있음")
        return
    image0 = images[0]

    print("images[0] 최상위 키 목록:", sorted(image0.keys()))

    fields = image0.get("fields")
    if fields is None:
        print("fields 키 없음")
        return
    print("fields 개수:", len(fields))

    if fields:
        print("fields[0] pretty print:")
        print(json.dumps(fields[0], ensure_ascii=False, indent=2))

        bp = fields[0].get("boundingPoly")
        if bp is None:
            print("fields[0]에 boundingPoly 없음")
        else:
            vertices = bp.get("vertices")
            print("boundingPoly.vertices 길이:", len(vertices) if vertices is not None else "vertices 키 없음")
    else:
        print("fields가 비어있어 fields[0] pretty print 생략")

    known_keys = {"inferText", "inferConfidence", "lineBreak", "boundingPoly", "type"}
    extra_keys = set()
    for f in fields:
        extra_keys |= (set(f.keys()) - known_keys)
    if extra_keys:
        sample_key = next(iter(extra_keys))
        sample_field = next(f for f in fields if sample_key in f)
        print(f"enableTableDetection 등으로 생긴 것으로 보이는 추가 키: {sorted(extra_keys)}")
        print(f"  샘플 ({sample_key}):", sample_field.get(sample_key))
    else:
        print("알려진 키(inferText/inferConfidence/lineBreak/boundingPoly/type) 외 추가 키 없음")

    confidences = [f.get("inferConfidence") for f in fields if f.get("inferConfidence") is not None]
    if confidences:
        print(f"inferConfidence min/median/max: "
              f"{min(confidences):.4f} / {statistics.median(confidences):.4f} / {max(confidences):.4f}")
    else:
        print("inferConfidence 값 없음")

    line_break_count = sum(1 for f in fields if f.get("lineBreak") is True)
    print("lineBreak=true인 필드 개수:", line_break_count)


def main():
    if len(sys.argv) != 2:
        print("사용법: python scripts/clova_probe.py <image_path>")
        sys.exit(1)
    image_path = sys.argv[1]
    if not os.path.isfile(image_path):
        print(f"이미지 파일을 찾을 수 없음: {image_path}")
        sys.exit(1)

    invoke_url = os.getenv("CLOVA_INVOKE_URL")
    secret_key = os.getenv("CLOVA_SECRET_KEY")
    if not invoke_url or not secret_key:
        print("CLOVA_INVOKE_URL 또는 CLOVA_SECRET_KEY가 .env에 없음")
        sys.exit(1)

    os.makedirs(OUT_DIR, exist_ok=True)
    ts = int(time.time())

    print("이미지 리사이즈 중 (장축 1960px)...")
    resized_bytes = _resize_for_ocr(image_path)
    resized_img = Image.open(io.BytesIO(resized_bytes))
    print(f"리사이즈 후 이미지 크기: {resized_img.size[0]}x{resized_img.size[1]}")

    resized_path = os.path.join(OUT_DIR, f"resized_{ts}.jpg")
    with open(resized_path, "wb") as f:
        f.write(resized_bytes)
    print(f"리사이즈 이미지 저장: {resized_path}")

    # 표 형식 문제 몇 개만 영향받는 옵션이라(대다수 문제는 무관), 콘솔 도메인
    # 토글까지 켜야 하는 번거로움 대비 이득이 적다고 판단해 끄기로 결정함 (2026-08-25).
    print("\nClova 호출 중 (enableTableDetection=false)...")
    status, data, raw_text = _call_clova(invoke_url, secret_key, resized_bytes, enable_table=False)
    print(f"HTTP 상태 코드: {status}")

    if status != 200 or data is None:
        print("실패. 응답 본문(원문):", raw_text[:2000])
        print("\n실행 실패로 보고함 (성공으로 보고하지 않음).")
        sys.exit(1)

    raw_path = os.path.join(OUT_DIR, f"clova_raw_{ts}.json")
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"원본 JSON 저장: {raw_path}")

    _summarize(data)


if __name__ == "__main__":
    main()
