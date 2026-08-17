from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import google.generativeai as genai
import httpx
import json
import os
from dotenv import load_dotenv

# vision_processor.py에서 함수 직접 import
from vision_processor import analyze_image

load_dotenv()

app = FastAPI()

# CORS 설정 (프론트 localhost:5173 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Gemini 설정
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-2.5-flash")

# Clova OCR 설정
CLOVA_INVOKE_URL = os.getenv("CLOVA_INVOKE_URL")
CLOVA_SECRET_KEY = os.getenv("CLOVA_SECRET_KEY")


# 요청 바디 모델
class AnalyzeRequest(BaseModel):
    image: str
    userQuestion: str = "이 문제 좀 알려줘"


async def request_clova_ocr(base64_image: str) -> str:
    """Clova OCR 호출"""
    import base64
    import time

    # base64 앞부분 제거
    if "base64," in base64_image:
        image_data = base64_image.split(",")[1]
    else:
        image_data = base64_image

    message = {
        "images": [{"format": "png", "name": "study_material"}],
        "requestId": str(int(time.time())),
        "version": "V2",
        "timestamp": int(time.time()),
    }

    image_bytes = base64.b64decode(image_data)

    async with httpx.AsyncClient() as client:
        response = await client.post(
            CLOVA_INVOKE_URL,
            headers={"X-OCR-SECRET": CLOVA_SECRET_KEY},
            files={"file": ("image.png", image_bytes, "image/png")},
            data={"message": json.dumps(message)},
        )
        result = response.json()

    ocr_text = " ".join(
        field["inferText"]
        for field in result["images"][0]["fields"]
    )
    return ocr_text


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

    # 2단계: Clova OCR
    print("2. OCR 요청 시작...")
    ocr_text = await request_clova_ocr(req.image)
    print("OCR 인식 성공")

    # 3단계: Gemini 해설 생성
    print("3. Gemini 해설 생성 시작...")
    finger_x = vision_result["x"] if vision_result["finger_detected"] else None
    finger_y = vision_result["y"] if vision_result["finger_detected"] else None

    prompt = f"""
당신은 야학 어르신을 위한 선생님입니다.

[규칙]
- 쉬운 우리말 사용
- 친근한 말투
- 인사말 없이 바로 답만 출력
- 아래 형식을 반드시 지켜주세요. 형식 외 문장 절대 추가 금지

[출력 형식 - 이 틀 그대로만 출력]
1. 문제 해석: [한 줄]
2. 정답: (번호) 단어 - 뜻
이유: [한 줄]
3. 나머지 보기:
① 단어 - 뜻
③ 단어 - 뜻
④ 단어 - 뜻

[이미지 내용(OCR)]
{ocr_text}

[손가락 위치]
{f"x={finger_x}px, y={finger_y}px 근처 문제" if finger_x is not None else "전체 문제 설명"}

[질문]
"{req.userQuestion}"
"""

    result = model.generate_content(prompt)
    response_text = result.text
    print("4. Gemini 응답 성공!")

    return {
        "status": "success",
        "explanation": response_text,
        "finger_detected": vision_result["finger_detected"],
        "coordinates": {"x": finger_x, "y": finger_y},
        "blur_score": vision_result["blur_score"],
        "brightness": vision_result["brightness"],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
