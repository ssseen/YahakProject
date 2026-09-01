from fastapi import FastAPI, UploadFile, File
import librosa
import io
import torch
from transformers import WhisperForConditionalGeneration, WhisperProcessor

app = FastAPI()

# 1. AI 모델 세팅 
MODEL_PATH = "/content/drive/MyDrive/whisper-saturi-lora/checkpoint-200"
processor = WhisperProcessor.from_pretrained(MODEL_PATH)
model = WhisperForConditionalGeneration.from_pretrained(MODEL_PATH).to("cuda")

@app.post("/transcribe")
async def transcribe_audio(audio_file: UploadFile = File(...)):
    # 2. 프론트엔드가 보낸 파일 읽어오기
    contents = await audio_file.read()

    # 3. 전처리: 16000Hz로 맞추기
    audio_data, _ = librosa.load(io.BytesIO(contents), sr=16000)

    # 4. 모델 입력용 텐서 변환
    inputs = processor(audio_data, sampling_rate=16000, return_tensors="pt").input_features.to("cuda")

    # 5. 변환 실행
    with torch.no_grad():
        predicted_ids = model.generate(inputs)
    
    transcription = processor.batch_decode(predicted_ids, skip_special_tokens=True)[0]

    # 6. 프론트엔드로 텍스트 반환
    return {"text": transcription}