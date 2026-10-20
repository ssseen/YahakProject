# Whisper 노인 발화 STT (LoRA)

## 모델
- 베이스: `openai/whisper-small`
- LoRA: r=32, alpha=64, dropout 0.05, 대상 q/k/v/out_proj, fc1, fc2 (학습 파라미터 5.09%)
- 데이터: AI Hub 노인남여 자유대화 음성(음성수집도구) – train 99.4h / 179명, valid 4.0h / 5명
- 학습: lr 2e-4, batch 16(8×2), fp16, 조기 종료 → step 4500 (valid loss 0.1711)

## 성능 (AI Hub 공식 Validation, 학습과 겹치지 않는 화자 18명 × 100발화)
| | CER |
|---|---|
| whisper-small 원본 | 10.31% |
| LoRA 파인튜닝 | **6.41%** (상대 37.8% 감소) |

## 파일
| 파일 | 설명 |
|---|---|
| `adapter_config.json`, `adapter_model.safetensors` | LoRA 어댑터 (Drive `whisper-lora-ko-lr2e4/adapter`) |
| `whisper_backend.py` | STT 서버 (`POST /transcribe`, `GET /health`) |
| `Dockerfile`, `requirements.txt` | Cloud Run 배포용 |

로컬 백엔드(`backend/app/stt_client.py`)도 이 폴더의 어댑터를 그대로 읽는다.

## Cloud Run 배포 (레포 루트에서)
```bash
gcloud run deploy yahak-stt \
  --source whisper \
  --region asia-northeast3 \
  --memory 4Gi --cpu 4 \
  --min-instances 1 --max-instances 2 \
  --cpu-boost \
  --allow-unauthenticated
```
- 배포 후 나온 URL을 `frontend/js/pages/voice-processing.js`의 `STT_BASE`에 넣기
- `--min-instances 1`: 콜드 스타트(모델 로딩 ~30초) 방지. 시연 끝나면 `0`으로 내려 비용 절약
  ```bash
  gcloud run services update yahak-stt --region asia-northeast3 --min-instances 0
  ```
- 확인: `curl https://<URL>/health` → `{"ok": true, "device": "cpu"}`
