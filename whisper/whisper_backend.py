"""
노인 발화 Whisper STT 서버 (Cloud Run 단독 서비스)

- 베이스: openai/whisper-small (Docker 빌드 때 이미지 안에 미리 받아둠)
- 어댑터: 이 폴더의 adapter_config.json + adapter_model.safetensors (LoRA)
- 기동 시 베이스+LoRA를 merge 해서 메모리에 올려둠 (추론 ~15% 빠름)

POST /transcribe  (multipart, 필드명 audio_file [+ prompt, compare])  -> {"text": "...", ...}
  - prompt: 시험지 문항에서 뽑은 낱말들(힌트). 주면 Whisper가 그 낱말 쪽으로 알아듣는다
  - compare=1: 힌트 없이도 한 번 더 돌려서 둘 다 돌려줌 (비교 측정용, 느려짐)
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
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from peft import PeftModel
from transformers import WhisperForConditionalGeneration, WhisperProcessor

BASE_MODEL = os.getenv("BASE_MODEL", "openai/whisper-small")
ADAPTER_DIR = os.getenv("ADAPTER_DIR", os.path.dirname(os.path.abspath(__file__)))
SR = 16000
MAX_SEC = 30  # Whisper 입력 창. 넘는 부분은 잘림
# 힌트 프롬프트 (2026-11-03): 시험 용어 오인식("빗살무늬 토기" -> "비싸 할머니") 대응.
# WHISPER_HINT=0 으로 배포하면 앱이 힌트를 보내도 무시 (되돌리기용)
USE_HINT = os.getenv("WHISPER_HINT", "1") != "0"
# 프롬프트가 길면 Whisper가 프롬프트를 따라 쓰거나 느려지므로 앞부분만 사용 (모델 한도 223)
PROMPT_MAX_TOKENS = int(os.getenv("WHISPER_PROMPT_MAX_TOKENS", "120"))

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
    transcribe_pcm(np.zeros(SR, dtype=np.float32), "검정고시 문제")  # 힌트 경로도 미리 한 번
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


def clean_text(text: str) -> str:
    text = NOISE_TAG.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def transcribe_pcm(pcm: np.ndarray, prompt: str | None = None) -> str:
    p, m = state["processor"], state["model"]
    feats = p(pcm, sampling_rate=SR, return_tensors="pt").input_features.to(state["device"])
    kwargs = {}
    prompt_text = ""
    if prompt:
        ids = p.get_prompt_ids(prompt, return_tensors="pt")[: 1 + PROMPT_MAX_TOKENS]  # [startofprev, 낱말...]
        kwargs["prompt_ids"] = ids.to(state["device"])
        prompt_text = p.tokenizer.decode(ids[1:], skip_special_tokens=True).strip()
    with torch.inference_mode():
        out = m.generate(feats, language="ko", task="transcribe", **kwargs)
    text = p.batch_decode(out, skip_special_tokens=True)[0].strip()
    # transformers 버전에 따라 결과 앞에 프롬프트가 붙어 나오는 경우가 있어 떼어 냄
    if prompt_text and text.startswith(prompt_text):
        text = text[len(prompt_text):]
    return clean_text(text)


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
def transcribe(
    audio_file: UploadFile = File(...),
    prompt: str | None = Form(None),
    compare: bool = Form(False),
):
    # def(동기) 엔드포인트 -> FastAPI가 스레드풀에서 돌려서 추론 중에도 /health 응답 가능
    data = audio_file.file.read()
    if not data:
        raise HTTPException(422, "빈 오디오입니다.")
    t = time.perf_counter()
    pcm = decode_audio(data)
    t_decode = time.perf_counter() - t

    hint = (prompt or "").strip() if USE_HINT else ""
    t1 = time.perf_counter()
    text = transcribe_pcm(pcm, hint or None)
    if hint and not text:  # 힌트 때문에 빈 결과가 나오면 힌트 없이 다시
        text = transcribe_pcm(pcm)
    ms = round((time.perf_counter() - t1) * 1000)
    resp = {"text": text, "hint_used": bool(hint), "ms": ms}

    if compare and hint:
        t2 = time.perf_counter()
        resp["text_nohint"] = transcribe_pcm(pcm)
        resp["ms_nohint"] = round((time.perf_counter() - t2) * 1000)

    print(f"[STT] {len(pcm) / SR:.1f}s 음성 (디코딩 {t_decode:.2f}s) -> {ms / 1000:.2f}s "
          f"힌트={'O' if hint else 'X'}: {text!r}"
          + (f" | 힌트 없이 {resp['ms_nohint'] / 1000:.2f}s: {resp['text_nohint']!r}" if "text_nohint" in resp else ""),
          flush=True)
    return resp
