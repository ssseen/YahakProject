import base64
import os
import tempfile
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

from vision_processor import analyze_image
from pipeline import run_pipeline, check_without_finger, warmup_pinecone
from app.stt_client import SttError
from app.stt_client import preload as preload_stt
from app.stt_client import transcribe as transcribe_audio

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # STT 모델 로딩(CPU 약 30초)을 첫 /transcribe 요청 대신 서버 기동 시점에 백그라운드로
    # 끝내둔다. 스레드라서 서버는 바로 요청을 받고, /api/analyze는 영향 없음.
    threading.Thread(target=preload_stt, name="stt-preload", daemon=True).start()
    # Pinecone 첫 검색의 연결 준비(약 3초)도 기동 시점에 끝내둔다.
    threading.Thread(target=warmup_pinecone, name="pinecone-warmup", daemon=True).start()
    yield


app = FastAPI(lifespan=lifespan)

_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
os.makedirs(os.path.join(_STATIC_DIR, "diagrams"), exist_ok=True)
app.mount("/diagrams", StaticFiles(directory=os.path.join(_STATIC_DIR, "diagrams")), name="diagrams")

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5500",
        "https://ssseen.github.io",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_VALID_LEVELS = { "초졸", "중졸", "고졸" }

class CheckResult(BaseModel):
    """촬영 직후 검사(checkOnly) 응답의 finger_detected/x/y - 프론트가 그대로 돌려보낸다."""
    finger_detected: bool
    x: int | None = None
    y: int | None = None


class AnalyzeRequest(BaseModel):
    image: str
    userQuestion: str = "이 문제 좀 알려줘"
    checkOnly: bool = False
    userLevel: str | None = None
    checkResult: CheckResult | None = None


def _save_base64_image(base64_image: str) -> str:
    if "base64," in base64_image:
        image_data = base64_image.split(",", 1)[1]
    else:
        image_data = base64_image
    image_bytes = base64.b64decode(image_data)

    fd, tmp_path = tempfile.mkstemp(suffix=".png")
    with os.fdopen(fd, "wb") as f:
        f.write(image_bytes)
    return tmp_path


@app.post("/api/analyze")
async def analyze(req: AnalyzeRequest):
    # 1단계: 이미지 품질 검증 + 손가락 좌표 추출 (OpenCV)
    t_request = time.perf_counter()
    # 단계별 소요 시간(초) - 응답의 "timings"로 내려보낸다 (속도 측정용, 2026-10-26)
    timings = {}
    print(f"1. 이미지 분석 시작... (checkOnly={req.checkOnly}, userQuestion={req.userQuestion!r})")
    if not req.checkOnly and req.checkResult is not None:
        # 같은 사진을 촬영 직후 검사에서 이미 analyze_image로 검사했다 - 그 결과를 프론트가
        # 돌려보냈으므로 다시 돌리지 않는다 (예전엔 화질검사+손끝검출이 요청마다 2번 돌았음).
        vision_result = {"status": "success", **req.checkResult.model_dump()}
        print("비전 결과(촬영 검사 결과 재사용):", vision_result)
    else:
        t_vision = time.perf_counter()
        vision_result = analyze_image(req.image)
        timings["analyze_image"] = round(time.perf_counter() - t_vision, 3)
        print("비전 결과:", vision_result)

    if vision_result["status"] == "retake":
        return {
            "status": "retake",
            "message": vision_result["message"],
            "blur_score": vision_result["blur_score"],
            "brightness": vision_result["brightness"],
            "timings": {**timings, "server_total": round(time.perf_counter() - t_request, 3)},
        }

    if vision_result["status"] == "error":
        raise HTTPException(status_code=500, detail=vision_result["message"])

    # 사진 촬영 직후 화질/손가락 검사만 먼저 수행하는 경우 제미나이를 돌리지 않고 즉시 응답
    if req.checkOnly:
        # 손끝이 없으면 사진에 문제가 하나뿐일 때만 통과 - 여러 개면 여기서 바로 다시 찍기 안내
        if not vision_result["finger_detected"]:
            image_path = _save_base64_image(req.image)
            try:
                fail = check_without_finger(image_path, timings)
            finally:
                os.remove(image_path)
            if fail is not None:
                fail["timings"] = {**timings, "server_total": round(time.perf_counter() - t_request, 3)}
                return fail
        timings["server_total"] = round(time.perf_counter() - t_request, 3)
        print(f"   [시간] {timings}")
        return {
            "status": "checked",
            "finger_detected": vision_result["finger_detected"],
            "x": vision_result.get("x"),
            "y": vision_result.get("y"),
            "timings": timings,
        }

    # 2단계: 이미지 + 음성 질문(userQuestion)을 동시에 넣어 해설 파이프라인 실행
    print("2. 해설 파이프라인 시작 (이미지 + 음성 질문 동시 처리)...")
    image_path = _save_base64_image(req.image)
    try:
        if vision_result["finger_detected"]:
            x, y = vision_result["x"], vision_result["y"]
        else:
            x, y = None, None
            
        user_level = req.userLevel if req.userLevel in _VALID_LEVELS else None
        result = run_pipeline(image_path, x, y, user_question=req.userQuestion, user_level=user_level)
    finally:
        os.remove(image_path)

    result["timings"] = {**timings, **result.get("timings", {}),
                         "server_total": round(time.perf_counter() - t_request, 3)}
    print("3. 해설 파이프라인 완료:", result.get("status"))
    return result


@app.post("/transcribe")
async def transcribe(audio_file: UploadFile = File(...)):
    audio_bytes = await audio_file.read()
    print(f"1. 음성 수신: {audio_file.filename} ({len(audio_bytes)} bytes)")
    try:
        text = transcribe_audio(audio_bytes)
    except SttError as e:
        print("STT 오류:", e)
        raise HTTPException(status_code=422, detail=str(e))
    print(f"2. 인식 결과: {text!r}")
    return {"text": text}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)