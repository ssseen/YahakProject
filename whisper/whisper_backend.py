"""
노인 발화 Whisper STT 서버 (Cloud Run 단독 서비스)

- 베이스: openai/whisper-small (Docker 빌드 때 이미지 안에 미리 받아둠)
- 어댑터: 이 폴더의 adapter_config.json + adapter_model.safetensors (LoRA)
- 기동 시 베이스+LoRA를 merge 해서 메모리에 올려둠 (추론 ~15% 빠름)

POST /transcribe  (multipart, 필드명 audio_file)  -> {"text": "..."}
GET  /health                                     -> {"ok": true, "device": "cpu"}

로컬 실행: uvicorn whisper_backend:app --port 8080
"""
import io
import os
import re
import time
from contextlib import asynccontextmanager

import av
import numpy as np
import torch
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from peft import PeftModel
from transformers import WhisperForConditionalGeneration, WhisperProcessor

BASE_MODEL = os.getenv("BASE_MODEL", "openai/whisper-small")
ADAPTER_DIR = os.getenv("ADAPTER_DIR", os.path.dirname(os.path.abspath(__file__)))
SR = 16000
MAX_SEC = 30  # Whisper 입력 창. 넘는 부분은 잘림

# 학습 라벨에 섞여 있던 잡음 태그(FP 머뭇거림, SN/SP/NO 잡음) - 출력에 나오면 제거
NOISE_TAG = re.compile(r"\b(?:FP|SN|SP|NO)\b/?")

state = {}


def load_model():
    t = time.perf_counter()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    processor = WhisperProcessor.from_pretrained(BASE_MODEL)
    base = WhisperForConditionalGeneration.from_pretrained(BASE_MODEL)
    model = PeftModel.from_pretrained(base, ADAPTER_DIR).merge_and_unload()
    model.generation_config.forced_decoder_ids = None
    model.to(device).eval()
    state.update(processor=processor, model=model, device=device)

    # 워밍업: 첫 요청만 느린 비용을 기동 때 미리 치름
    transcribe_pcm(np.zeros(SR, dtype=np.float32))
    print(f"[STT] 모델 로딩 완료 {time.perf_counter() - t:.1f}s device={device}", flush=True)


def decode_audio(data: bytes) -> np.ndarray:
    """브라우저 MediaRecorder(webm/opus, mp4 등) -> 16kHz mono float32. ffmpeg 설치 불필요(PyAV)"""
    try:
        container = av.open(io.BytesIO(data))
    except av.error.FFmpegError as e:
        raise HTTPException(422, f"오디오 파일을 열지 못했습니다: {e}")
    if not container.streams.audio:
        raise HTTPException(422, "오디오 트랙이 없습니다.")

    resampler = av.AudioResampler(format="s16", layout="mono", rate=SR)
    chunks = []
    for packet in container.demux(container.streams.audio[0]):
        for frame in packet.decode():
            for r in resampler.resample(frame):
                chunks.append(r.to_ndarray())
    for r in resampler.resample(None):  # 리샘플러에 남은 꼬리 비우기
        chunks.append(r.to_ndarray())
    container.close()

    if not chunks:
        raise HTTPException(422, "오디오에서 소리를 추출하지 못했습니다.")
    pcm = np.concatenate(chunks, axis=1).flatten().astype(np.float32) / 32768.0
    return pcm[: SR * MAX_SEC]


def transcribe_pcm(pcm: np.ndarray) -> str:
    p, m = state["processor"], state["model"]
    feats = p(pcm, sampling_rate=SR, return_tensors="pt").input_features.to(state["device"])
    with torch.inference_mode():
        ids = m.generate(feats, language="ko", task="transcribe")
    text = p.batch_decode(ids, skip_special_tokens=True)[0]
    text = NOISE_TAG.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_model()  # 동기 로딩: Cloud Run은 로딩이 끝나야 트래픽을 보냄
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv(
        "ALLOW_ORIGINS",
        "https://ssseen.github.io,http://localhost:5173,http://127.0.0.1:5500",
    ).split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"ok": "model" in state, "device": state.get("device")}


@app.post("/transcribe")
def transcribe(audio_file: UploadFile = File(...)):
    # def(동기) 엔드포인트 -> FastAPI가 스레드풀에서 돌려서 추론 중에도 /health 응답 가능
    data = audio_file.file.read()
    if not data:
        raise HTTPException(422, "빈 오디오입니다.")
    t = time.perf_counter()
    pcm = decode_audio(data)
    text = transcribe_pcm(pcm)
    print(f"[STT] {len(pcm) / SR:.1f}s 음성 -> {time.perf_counter() - t:.1f}s: {text!r}", flush=True)
    return {"text": text}
