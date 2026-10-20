FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    HF_HOME=/models \
    HF_HUB_OFFLINE=0

WORKDIR /app

# CPU 전용 torch (CUDA 버전보다 이미지가 몇 GB 작음)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 베이스 모델을 이미지에 미리 받아둠 -> 컨테이너 뜰 때마다 다운로드 안 함
RUN python -c "from transformers import WhisperProcessor, WhisperForConditionalGeneration as W; \
WhisperProcessor.from_pretrained('openai/whisper-small'); W.from_pretrained('openai/whisper-small')"
ENV HF_HUB_OFFLINE=1

COPY adapter_config.json adapter_model.safetensors whisper_backend.py ./

CMD exec uvicorn whisper_backend:app --host 0.0.0.0 --port ${PORT:-8080}
