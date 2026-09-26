"""
사투리 인식 Whisper STT 호출.

베이스 모델은 openai/whisper-small, `whisper/` 폴더(레포 루트, backend 밖)에는
peft LoRA 어댑터(adapter_config.json/adapter_model.safetensors)만 있고 토크나이저
파일은 없다 - LoRA가 q_proj/v_proj만 건드려 어휘는 그대로이므로 프로세서(피처
추출기+토크나이저)는 베이스 모델 것을 그대로 쓴다(whisper/preprocessor_config.json과
설정이 동일함을 확인함).

원본 whisper/whisper_backend.py는 Colab 체크포인트 경로(Google Drive)와
`.to("cuda")`를 하드코딩한 별도 FastAPI 앱이었다 - 로컬 실행을 위해 이 모듈에서
로컬 어댑터 경로 + CPU/GPU 자동 감지로 옮겨왔다.

torch/peft/transformers는 requirements-cloudrun.txt에 없다(용량 때문에 배포
이미지에선 빼기로 한 easyocr/torch 방침, HANDOFF.md 3번 섹션과 동일한 이유) -
그래서 이 모듈의 무거운 import를 파일 최상단이 아니라 `_load()` 안에 둔다. main.py가
이 모듈을 top-level import해도 실제로 torch를 끌어오는 건 첫 `/transcribe` 호출
시점뿐이라, 클라우드 배포 환경(STT 미지원)에서도 앱 자체는 정상 기동한다.
"""
import io
import os
import threading
from typing import Any

import numpy as np

_BASE_MODEL = "openai/whisper-small"
_ADAPTER_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "whisper")
)
_SAMPLE_RATE = 16000

_lock = threading.Lock()
_processor: Any = None
_model: Any = None
_device: str | None = None


class SttError(Exception):
    pass


def _load():
    global _processor, _model, _device
    if _model is not None:
        return
    with _lock:
        if _model is not None:
            return
        if not os.path.isdir(_ADAPTER_DIR):
            raise SttError(f"LoRA 어댑터 폴더를 찾을 수 없습니다: {_ADAPTER_DIR}")

        try:
            import torch
            from peft import PeftModel
            from transformers import WhisperForConditionalGeneration, WhisperProcessor
        except ImportError as e:
            raise SttError(
                "음성 인식에 필요한 패키지가 설치돼 있지 않습니다"
                " (torch/transformers/peft) - 로컬 개발 환경에서만 지원됩니다."
            ) from e

        device = "cuda" if torch.cuda.is_available() else "cpu"
        processor = WhisperProcessor.from_pretrained(_BASE_MODEL)
        base_model = WhisperForConditionalGeneration.from_pretrained(_BASE_MODEL)
        model = PeftModel.from_pretrained(base_model, _ADAPTER_DIR)
        model.to(device)
        model.eval()

        _processor, _model, _device = processor, model, device


def _decode_audio(audio_bytes: bytes) -> np.ndarray:
    """
    브라우저 MediaRecorder가 보내는 webm/opus 등 컨테이너를 16kHz mono float32
    PCM으로 디코딩한다. 시스템에 ffmpeg가 설치돼 있지 않아도 되도록(librosa/
    audioread는 webm 디코딩에 시스템 ffmpeg가 필요함) PyAV를 쓴다 - ffmpeg
    라이브러리를 wheel에 정적으로 포함하고 있어 pip install만으로 동작한다.
    """
    import av  # noqa: PLC0415 - 무거운 의존성, 실제 STT 호출 시점에만 import

    try:
        container = av.open(io.BytesIO(audio_bytes))
    except av.error.FFmpegError as e:
        raise SttError(f"오디오 파일을 열지 못했습니다: {e}") from e

    if not container.streams.audio:
        raise SttError("오디오 트랙이 없습니다.")

    stream = container.streams.audio[0]
    resampler = av.AudioResampler(format="s16", layout="mono", rate=_SAMPLE_RATE)

    chunks = []
    for packet in container.demux(stream):
        for frame in packet.decode():
            for resampled in resampler.resample(frame):
                chunks.append(resampled.to_ndarray())
    container.close()

    if not chunks:
        raise SttError("오디오에서 소리를 추출하지 못했습니다.")

    pcm = np.concatenate(chunks, axis=1).flatten()
    return pcm.astype(np.float32) / 32768.0


def transcribe(audio_bytes: bytes) -> str:
    """오디오 바이트를 받아 인식된 텍스트를 반환한다."""
    import torch

    _load()
    audio = _decode_audio(audio_bytes)

    inputs = _processor(
        audio, sampling_rate=_SAMPLE_RATE, return_tensors="pt"
    ).input_features.to(_device)

    with torch.no_grad():
        predicted_ids = _model.generate(inputs)

    text = _processor.batch_decode(predicted_ids, skip_special_tokens=True)[0]
    return text.strip()
