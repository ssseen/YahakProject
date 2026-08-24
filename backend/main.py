import base64
import os
import tempfile

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

# vision_processor.py에서 함수 직접 import
from vision_processor import analyze_image
from pipeline import run_pipeline

load_dotenv()

app = FastAPI()

# CORS 설정 (프론트 localhost:5173, VSCode Live Server 127.0.0.1:5500 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5500"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 요청 바디 모델
class AnalyzeRequest(BaseModel):
    image: str
    userQuestion: str = "이 문제 좀 알려줘"


def _save_base64_image(base64_image: str) -> str:
    """
    base64 이미지 문자열을 임시 파일로 저장하고 경로를 반환한다.
    run_pipeline은 (메모리 상의 이미지가 아니라) 파일 경로를 받으므로 필요하다.
    호출부에서 다 쓴 뒤 반드시 os.remove로 지워야 한다.
    """
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
    print("1. 이미지 분석 시작...")
    vision_result = analyze_image(req.image)
    print("비전 결과:", vision_result)

    # 품질 불량 → 재촬영 요청
    if vision_result["status"] == "retake":
        return {
            "status": "retake",
            "message": vision_result["message"],
            "blur_score": vision_result["blur_score"],
            "brightness": vision_result["brightness"],
        }

    # 시스템 오류
    if vision_result["status"] == "error":
        raise HTTPException(status_code=500, detail=vision_result["message"])

    # 2단계: 해설 파이프라인 실행 (OCR/분류/해설을 pipeline.py가 전부 처리 - 해설 응답
    # 명세서의 status/type/subject/... 구조를 그대로 반환한다)
    print("2. 해설 파이프라인 시작...")
    image_path = _save_base64_image(req.image)
    try:
        if vision_result["finger_detected"]:
            x, y = vision_result["x"], vision_result["y"]
        else:
            # 손가락을 못 찾아도 analyze_image는 재촬영 요청 없이 success로 넘어온다.
            # 가짜 좌표(예: 이미지 중앙)를 만들어서 넘기면 run_pipeline이 그 근처를 "문제
            # 하나"로 잘라내버려서 문제지에 여러 문제가 있을 때 엉뚱한 문제를 해설하게
            # 되므로, x,y 그대로 None을 넘긴다 - run_pipeline이 이 경우 crop을 건너뛰고
            # 원본 이미지 전체를 쓴다 (pipeline.py 참고).
            x, y = None, None

        result = run_pipeline(image_path, x, y, user_question=req.userQuestion)
    finally:
        os.remove(image_path)

    print("3. 해설 파이프라인 완료:", result.get("status"))
    return result


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
