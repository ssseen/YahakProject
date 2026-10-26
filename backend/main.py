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
from pipeline import (
    run_pipeline, check_without_finger, warmup_pinecone, start_session, run_session, _retake_response,
)
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
    image: str | None = None  # sessionId로 해설 요청할 때는 생략 가능
    userQuestion: str = "이 문제 좀 알려줘"
    checkOnly: bool = False
    userLevel: str | None = None
    checkResult: CheckResult | None = None
    sessionId: str | None = None  # 촬영 검사 응답의 sessionId - 주면 사진 없이 미리 처리 결과로 해설
    # checkOnly와 같이 true로 보내면 통과 시 sessionId를 발급하고 해설 앞단계를 미리 처리한다.
    # 기본 false - sessionId를 안 쓰는 프론트에서 미리 처리를 돌리면 OCR(Clova)만 두 번 하게 되므로
    # (2026-10-26 배포 로그로 확인) 프론트가 sessionId를 쓸 준비가 됐다고 알릴 때만 한다.
    prepare: bool = False


def _decode_base64_image(base64_image: str) -> bytes:
    if "base64," in base64_image:
        base64_image = base64_image.split(",", 1)[1]
    return base64.b64decode(base64_image)


def _save_base64_image(base64_image: str) -> str:
    fd, tmp_path = tempfile.mkstemp(suffix=".png")
    with os.fdopen(fd, "wb") as f:
        f.write(_decode_base64_image(base64_image))
    return tmp_path


# async def가 아닌 일반 def - 안에서 OCR/Gemini 등 오래 걸리는 동기 작업을 하므로, async def면
# 한 요청이 처리되는 동안 서버의 다른 요청이 전부 멈췄다. def면 FastAPI가 스레드풀에서 돌린다.
@app.post("/api/analyze")
def analyze(req: AnalyzeRequest):
    t_request = time.perf_counter()
    # 단계별 소요 시간(초) - 응답의 "timings"로 내려보낸다 (속도 측정용, 2026-10-26)
    timings = {}

    # 촬영 검사 때 받은 sessionId로 온 해설 요청: 음성 녹음 동안 미리 처리해둔 결과로 Gemini만 부른다
    if not req.checkOnly and req.sessionId:
        print(f"해설 요청(세션 {req.sessionId[:8]}, userQuestion={req.userQuestion!r})")
        user_level = req.userLevel if req.userLevel in _VALID_LEVELS else None
        result = run_session(req.sessionId, user_question=req.userQuestion, user_level=user_level)
        if result is not None:
            result["timings"]["server_total"] = round(time.perf_counter() - t_request, 3)
            return result
        if not req.image:
            return _retake_response(reason="session_expired")
        print("   세션 없음 - 같이 온 사진으로 처음부터 처리")

    if not req.image:
        raise HTTPException(status_code=422, detail="image 또는 유효한 sessionId가 필요합니다")

    # 1단계: 이미지 품질 검증 + 손가락 좌표 추출 (OpenCV)
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
        # prepare=true면 음성 녹음하는 동안 해설 앞단계(OCR~Pinecone~빨간 박스)를 미리 돌린다
        session_id = None
        if req.prepare:
            session_id = start_session(
                _decode_base64_image(req.image),
                vision_result.get("x") if vision_result["finger_detected"] else None,
                vision_result.get("y") if vision_result["finger_detected"] else None,
            )
        timings["server_total"] = round(time.perf_counter() - t_request, 3)
        print(f"   [시간] {timings}" + (f" (세션 {session_id[:8]} 미리 처리 시작)" if session_id else ""))
        return {
            "status": "checked",
            "finger_detected": vision_result["finger_detected"],
            "x": vision_result.get("x"),
            "y": vision_result.get("y"),
            "sessionId": session_id,
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