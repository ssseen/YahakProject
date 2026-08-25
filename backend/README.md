# 야학 백엔드 (v2)

검정고시 문제지 사진을 찍어 손끝으로 짚은 문제를 인식하면, 유형을 분류하고 해설(텍스트/음성)을 생성해주는 API 서버.

## v2 파이프라인 개요

```
OpenCV(사진 품질검사)
  → 장축 1960px 리사이즈 + 손끝 재검출
    → Clova OCR
      → question_locator (손끝 → 문항 번호/영역 특정, 자르지 않고 마킹만)
        → Pinecone 무필터 검색 1회 (top_k=10)
          → subject_router (과목 판정: 영어/수학/국사과)
            → Gemini 2차 호출 (유일한 LLM 호출, 해설 생성)
```

v1에서는 Gemini를 두 번(OCR용 1차 + 해설용 2차) 호출했는데, v2는 OCR을 Clova로 옮기고
문항 특정·과목 판정을 규칙 기반(정규식 + Pinecone 다수결)으로 처리해서 Gemini 호출이
2회 → 1회로 줄었다.

## 파일 맵

| 경로 | 역할 |
|---|---|
| `main.py` | FastAPI 엔트리포인트. `POST /api/analyze` |
| `pipeline.py` | v2 파이프라인 오케스트레이션 (`run_pipeline`) — 이 파일이 위 순서대로 나머지를 전부 호출한다 |
| `vision_processor.py` | OpenCV: 사진 품질 검증(블러/밝기), 손끝 좌표 검출(`find_finger_tip`) |
| `app/clova_client.py` | Clova OCR 호출 + 응답을 `Line` 목록으로 정규화. **EXIF 회전 보정 포함** (휴대폰 사진은 EXIF Orientation 태그로만 회전 정보를 갖고 실제 픽셀은 안 돌아가 있는 경우가 많음 — 이걸 안 하면 세로 사진이 옆으로 누운 채로 처리됨) |
| `app/question_locator.py` | Clova가 준 줄 목록 + 손끝 좌표로 "몇 번 문제인지" 특정. 번호 앵커(`1.`, `2.` 등) 탐지 → 앵커 위치로 컬럼(단) 구분 → 손끝에서 가장 가까운 줄이 속한 밴드를 문항으로 판정 |
| `app/subject_router.py` | Pinecone 검색 결과로 과목(영어/수학/국사과) 다수결 판정 + 라틴 비율/수식 밀도 가드 |
| `classifier.py` | v1 전용 필터 검색(`classify_problem`). v2 `pipeline.py`는 더 이상 안 씀 — Pinecone 클라이언트가 필요한 다른 곳에서 참고용으로 남아있음 |
| `guksagwa_explainer.py` | 국어/사회/과학 해설 생성 (Gemini 2차) |
| `english_explainer.py` | 영어 해설 생성 (Gemini 2차) — 지문/보기 토큰화 + 단어 뜻 팝업 데이터 포함 |
| `gemini_config.py` | Gemini 모델 클라이언트 공용 설정 |
| `answer_utils.py` | 정답 텍스트 정규화 (`{"number", "text"}` 형태로) |
| `experiments/` | v1 Gemini 1차(`problem_extractor.py`) + EasyOCR 대체 실험(`ocr_extractor.py`, `test_ocr_vs_gemini.py`). pipeline.py는 더 이상 안 쓰고, "왜 Clova로 바꿨는지" 근거 자료로 보존 |
| `scripts/clova_probe.py` | Clova 응답 구조 확인용 수동 스크립트. `out/`에 원본 JSON 저장 |
| `scripts/subject_eval.py` | Pinecone 인덱스를 평가셋 삼아 과목 판정 임계값을 leave-one-out으로 검증 |
| `tests/` | pytest. `question_locator`/`clova_client`/`subject_router` 단위 테스트 |
| `test_pipeline.py`, `test_illustration_pipeline.py` | v1 시절 수동 통합 테스트 스크립트 (구조 변경으로 일부 개념이 안 맞을 수 있음, 참고용) |

## 실행

```bash
cd backend
python -m venv venv && venv\Scripts\activate   # Windows
pip install -r requirements.txt
python main.py                                  # http://localhost:8000
```

`.env` 필요 (레포에는 없음, 각자 발급):
```
GEMINI_API_KEY=
PINECONE_API_KEY=
CLOVA_INVOKE_URL=
CLOVA_SECRET_KEY=
```

테스트: `pytest tests/` (네트워크 호출 없음, Gemini/Pinecone/Clova 전부 실제 호출 안 함)

## 확정된 설계 결정

- **Pinecone 유사도 임계값 0.25** — `scripts/subject_eval.py`로 3740건 leave-one-out 검증한 결과. 낮을수록 다수결 투표자가 많아져 오히려 더 정확함(정확도 98.66%로 최고)
- **Clova `enableTableDetection`은 끔** — 표 형식 문제 몇 개만 영향받는데 콘솔 도메인 설정까지 켜야 하는 번거로움 대비 이득이 적다고 판단
- **한국사·도덕은 스코프 제외** — Pinecone 인덱스에 해당 `subject` 값 자체가 없음(초/중졸 레벨은 한국사가 사회에 통합)
- **자르지 않고 마킹만** — Gemini 2차 호출에는 문항만 크롭한 이미지가 아니라 전체 페이지 + 빨간 박스를 보낸다. 박스 경계가 부정확해도 문맥이 안 잘려서, 크롭 방식보다 할루시네이션 여지가 적음

## 알려진 한계

- **수학 미지원** — `subject_router`가 "수학"으로 판정하면 `unsupported_subject` 응답만 반환. 해설 생성기 자체가 없음
- **`locate_confidence: "low"`인 경우 정확도 하락 가능** — 손끝이 애매한 위치(문항 경계 등)일 때. 실사용 중 이 값이 자주 `low`로 뜨면 `question_locator`의 밴드 판정 로직을 더 다듬어야 함
- **원문자(①②③④⑤) OCR 오인식** — Clova가 가끔 `④`를 그냥 숫자 `4`로 읽는다. `pipeline.py`의 `_split_passage_and_options`가 이 경우까지 보기 마커로 인정하도록 보완했지만, 완벽하지 않을 수 있음
- **회전된 사진** — `app/clova_client.py`가 EXIF Orientation은 보정하지만, EXIF 태그 자체가 없는데 실제로 옆으로 찍힌 사진(회전 정보가 아예 없는 경우)까지는 못 잡음
