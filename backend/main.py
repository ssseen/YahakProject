import base64
import os
import tempfile

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

from vision_processor import analyze_image
from pipeline import run_pipeline
from app.stt_client import SttError
from app.stt_client import transcribe as transcribe_audio

load_dotenv()

app = FastAPI()

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


class AnalyzeRequest(BaseModel):
    image: str
    userQuestion: str = "이 문제 좀 알려줘"
    checkOnly: bool = False


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
    print(f"1. 이미지 분석 시작... (checkOnly={req.checkOnly}, userQuestion={req.userQuestion!r})")
    vision_result = analyze_image(req.image)
    print("비전 결과:", vision_result)

    if vision_result["status"] == "retake":
        return {
            "status": "retake",
            "message": vision_result["message"],
            "blur_score": vision_result["blur_score"],
            "brightness": vision_result["brightness"],
        }

    if vision_result["status"] == "error":
        raise HTTPException(status_code=500, detail=vision_result["message"])

    # 사진 촬영 직후 화질/손가락 검사만 먼저 수행하는 경우 제미나이를 돌리지 않고 즉시 응답
    if req.checkOnly:
        return {
            "status": "checked",
            "finger_detected": vision_result["finger_detected"],
            "x": vision_result.get("x"),
            "y": vision_result.get("y"),
        }

    # 2단계: 이미지 + 음성 질문(userQuestion)을 동시에 넣어 해설 파이프라인 실행
    print("2. 해설 파이프라인 시작 (이미지 + 음성 질문 동시 처리)...")
    image_path = _save_base64_image(req.image)
    try:
        if vision_result["finger_detected"]:
            x, y = vision_result["x"], vision_result["y"]
        else:
            x, y = None, None

        result = run_pipeline(image_path, x, y, user_question=req.userQuestion)
    finally:
        os.remove(image_path)

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