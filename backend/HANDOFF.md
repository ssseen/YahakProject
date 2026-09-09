# 야학 백엔드 — 세션 인수인계 문서

**이 파일은 새 컴퓨터에서 클로드 코드(또는 사람)가 맥락을 잡기 위한 문서다.**
작성일: 2026-08-26. 2026-09-09 세션에서 P1(손끝 검출) 정확도 실측 검증 내용을
추가함(5번 섹션 4항, 8번 섹션 신설) — 이 시점까지 진행 상황을 전부 담았다.

새 컴퓨터에서 작업을 이어갈 클로드에게: 이 문서를 먼저 전체를 읽고 시작할 것. 여기
적힌 결정들(임계값, 옵션 켬/끔 등)은 전부 실측 검증을 거쳐 확정된 것이니 다시 묻지
말고 그대로 따를 것. 코드를 고칠 땐 "테스트 통과 = 완료"로 판단하지 말고, 가능하면
실제 사진으로 손끝 검출부터 끝까지 한 번 더 돌려볼 것 (이 문서에 적힌 버그 세 개가
전부 그렇게 발견됐다).

---

## 0. 지금 당장 할 일 / 이어서 할 일

**남은 건 P7(TTS, `app/tts_client.py`)뿐이다.** 나머지(P1~P6, P8)는 전부 완료해서
GitHub에 반영까지 끝났다.

P7은 **음성 모델이 아직 안 정해져서 보류 중**이다. 음성 담당자가 모델(Standard/
WaveNet/Neural2 중)을 확정하면 그때 시작한다. 담당자 결정이 나기 전에는 시작하지 말 것
(사용자가 "이건 나중에 할게"라고 명시적으로 미룸, 2026-08-26).

그 외에 **Pinecone 데이터 담당자가 유사문제 question/options 분리 작업을 해주기로
함**(6번 섹션 참고) — 이것도 데이터가 오기 전까지는 백엔드에서 할 일 없음, 대기.

---

## 1. 프로젝트 개요

검정고시 문제지 사진을 찍어 손끝으로 짚은 문제를 인식하면, 유형을 분류하고 해설
(텍스트, 나중엔 음성도)을 생성해주는 앱. 사용자(대화 상대)는 **유혜빈 — 백엔드 전담**
(팀원 없음, 파일 수정 전 담당자 재확인 불필요). 프론트/데이터 파이프라인은 GitHub
`ssseen` 계정이 담당.

**저장소**: `https://github.com/ssseen/YahakProject`
- `master` 브랜치: `backend/`(이 파이프라인) + `data_pinecone/`(파인콘 데이터 구축)
- `frontend-audio` 등 다른 브랜치: 프론트, 위스퍼 STT 등

**로컬 작업 폴더는 git 저장소가 아니다.** (예: 이 컴퓨터에서
`c:\Users\USER\Downloads\YahakProject-master\YahakProject-master`) GitHub에 반영하려면
별도 클론이 필요하다 (이 컴퓨터에서는 `YahakProject-github` 폴더가 그 역할이었음. 새
컴퓨터에서는 아래 2번 "새 컴퓨터 셋업" 참고).

---

## 2. 새 컴퓨터 셋업

### 방법 A — GitHub에서 새로 클론 (권장, 가장 깔끔함)

오늘 작업한 내용이 전부 `origin/master`에 푸시돼 있으므로, 이 방법이 가장 확실하다.

```bash
git clone https://github.com/ssseen/YahakProject.git
cd YahakProject/backend
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

### 방법 B — 지금 이 폴더를 통째로 복사

`results/`, `out/`, `.pytest_cache/`, `venv/`, `__pycache__/`는 전부 로컬 산출물이라
안 옮겨도 된다 (없어도 코드는 정상 동작, `results/`·`out/`은 실행하면 다시 생김).
`.env`는 **반드시 별도로** 옮기거나 새로 만들어야 한다 (git에 없음, 아래 3번 참고).

### `.env` — 어느 방법이든 직접 채워야 함 (GitHub에 없음)

```
GEMINI_API_KEY=
PINECONE_API_KEY=
CLOVA_INVOKE_URL=
CLOVA_SECRET_KEY=
```

- `GEMINI_API_KEY`: Google AI Studio에서 발급. 무료 티어는 **하루 20회 제한**
  (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`) — "분당 제한"처럼 보이는 에러
  메시지에 속지 말 것, 실제론 일일 쿼터.
- `PINECONE_API_KEY`: 기존 팀 Pinecone 프로젝트 키 (인덱스명 `geondi-questions`,
  namespace `questions`).
- `CLOVA_INVOKE_URL`/`CLOVA_SECRET_KEY`: 네이버클라우드 CLOVA OCR 콘솔에서 발급.
  Secret Key가 화면 캡처 등으로 노출되면 즉시 재발급할 것(종량제).

### 실행 확인

```bash
pytest tests/                    # 20개, 네트워크 호출 없음 (Gemini/Pinecone/Clova 다 안 부름)
python main.py                   # http://localhost:8000
```

---

## 3. v2 파이프라인 구조

```
OpenCV(사진 품질검사, main.py가 이미 처리)
  → 장축 1960px 리사이즈 + 손끝 재검출 (pipeline.py 내부)
    → Clova OCR (app/clova_client.py)
      → question_locator (app/question_locator.py) — 손끝 → 문항 번호/영역 특정
        → Pinecone 무필터 검색 1회, top_k=10 (pipeline.py)
          → subject_router (app/subject_router.py) — 과목 판정(영어/수학/국사과)
            → Gemini 2차 (english_explainer.py / guksagwa_explainer.py) — 유일한 LLM 호출
```

v1(예전)은 Gemini를 두 번(OCR용 1차 + 해설용 2차) 불렀는데, v2는 OCR을 Clova로 옮기고
문항 특정·과목 판정을 규칙 기반으로 처리해서 Gemini 호출이 2회→1회로 줄었다.

### 파일 맵

| 경로 | 역할 |
|---|---|
| `main.py` | FastAPI 엔트리포인트, `POST /api/analyze`. **건드리지 말 것** (팀 컨벤션상 원래도 다른 사람 파일은 아니지만, 이 파이프라인 전체가 이 파일의 호출 계약에 맞춰져 있음) |
| `pipeline.py` | v2 오케스트레이션. `run_pipeline()` |
| `vision_processor.py` | OpenCV: 품질검사, 손끝 검출(`find_finger_tip`) |
| `app/clova_client.py` | Clova 호출 + 정규화. **EXIF 회전 보정 포함** (아래 버그 1번 참고) |
| `app/question_locator.py` | 문항 특정. 번호 앵커 탐지 → 앵커 위치로 컬럼 구분 → 손끝 최근접 줄로 밴드 판정 |
| `app/subject_router.py` | 과목 판정 + 유사문제 선별 |
| `classifier.py` | v1 전용(필터 검색). v2 `pipeline.py`는 더 이상 안 씀, 참고용으로 남아있음 |
| `guksagwa_explainer.py` / `english_explainer.py` | Gemini 2차 해설 생성 |
| `gemini_config.py` | Gemini 모델 클라이언트 공용 설정 |
| `answer_utils.py` | 정답 텍스트 정규화 |
| `experiments/` | v1 Gemini 1차(`problem_extractor.py`) + EasyOCR 대체 실험. 참고용, pipeline.py는 안 씀 |
| `scripts/clova_probe.py` | Clova 응답 구조 확인용 수동 스크립트 |
| `scripts/subject_eval.py` | Pinecone을 평가셋 삼아 과목 판정 임계값 검증 (leave-one-out) |
| `tests/` | pytest 20개 |
| `results/` | **매 요청마다 자동 저장되는 실행 결과** (타임스탬프 파일명, git에 안 올라감) |
| `out/` | `clova_probe.py` 실행 시 원본 Clova 응답 저장 (git에 안 올라감) |

---

## 4. 확정된 설계 결정 (다시 묻지 말고 그대로 쓸 것)

- **Pinecone 과목판정 임계값 `THRESHOLD = 0.25`** (`app/subject_router.py`) —
  `scripts/subject_eval.py`로 3740건 leave-one-out 검증, 정확도 98.66%로 5개 후보 중
  최고. 임계값 낮을수록 다수결 투표자가 늘어 오히려 정확함(직관과 반대이니 유의).
- **Clova `enableTableDetection`은 끔** — 표 형식 문제 몇 개만 영향받고 콘솔 도메인
  토글까지 켜야 하는 번거로움 대비 이득이 적음. 표 문제 매칭 실패 사례가 실제로 쌓이면
  그때 재검토.
- **한국사·도덕은 스코프 제외** — Pinecone 인덱스에 그 `subject` 값 자체가 없음
  (과학770/사회770/국어770/영어770/수학660, 총 3740건). 초·중졸 레벨은 한국사가 사회에
  통합됨.
- **자르지 않고 마킹만** — Gemini 2차에는 문항만 크롭한 이미지가 아니라 전체 페이지 +
  빨간 박스를 보낸다. 박스가 부정확해도 문맥이 안 잘려서 할루시네이션 여지가 적음.
- **어휘 팝업은 기초 단어도 전부 포함** — 원래 "관사/전치사/be동사/기초대명사 제외"
  였는데 번복함. 학습자가 영어를 처음부터 다시 배우는 성인이라 who/i/you/she도 다
  포함해야 함 (`english_explainer.py`의 `[vocabulary 선정 기준]`).
- **유사문제는 1위 제외하고 2위부터, 점수 하한선 없음** (`app/subject_router.py`의
  `select_similar`) — **이유가 중요함**: 검정고시가 문제은행식이고 팀이 모의고사를
  전부 인덱싱해놔서, 사진 찍은 문제와 거의 동일한 문항이 인덱스에 이미 있는 게
  구조적으로 필연적이다. 그래서 1위는 항상 원본과 겹침 → 2위부터 써야 진짜 "다른
  유사문제"가 나옴. 점수가 낮아도(0.05든 뭐든) 무조건 2~4위를 보여주기로 함 — 정답
  판정과 달리 "연습용 문제 제시"라 정확도 손해를 감수해도 됨 (사용자 명시적 결정).
- **매 요청 결과는 `results/`에 자동 저장** — `save_path` 안 줘도 `pipeline.py`가
  타임스탬프 파일명으로 항상 저장한다 (이전엔 API 호출 결과가 응답만 하고 사라졌음).
- **`explanation_text`(내부) ↔ `explanation`(외부 API 계약) 분리** — 2차 해설 함수
  반환 dict엔 `explanation` 키가 없고 `explanation_text`만 있다. 최종 API 응답 필드명
  `explanation`은 프론트 계약이라 유지, `pipeline.py`가 매핑만 한다.

---

## 5. 실사진 테스트로 찾아서 고친 실전 버그 (합성 테스트로는 안 잡혔던 것들)

**핵심 교훈**: pytest가 다 통과해도 실제 사진으로는 깨질 수 있다. 아래 세 개는 전부
`영어1.jpg`, `영어4.jpg` 같은 실제 사진을 손끝 검출부터 Gemini 2차까지 진짜로 돌려보고서야
발견됐다.

1. **EXIF 회전 미보정** — 휴대폰 세로 사진은 파일 자체는 가로형으로 저장되고 EXIF
   Orientation 태그로만 회전 정보를 갖는 경우가 많다(사람 눈·뷰어는 자동 보정해서
   똑바로 보임). `PIL.Image.open()`은 이 태그를 무시해서, 코드 입장에선 사진이 옆으로
   누운 것처럼 처리돼 문항 특정이 완전히 실패했다. **수정**: `app/clova_client.py`의
   `resize_for_ocr`에 `ImageOps.exif_transpose()` 추가.
2. **컬럼(단) 판정이 카메라 각도 + 보기 격자 배치에 약함** — 번호 앵커들의 x좌표가
   카메라 각도 때문에 페이지 아래로 갈수록 서서히 밀리는데(실측 62px), 고정 허용오차
   비교 방식이라 못 버팀. 게다가 보기(①②③④)가 가로 격자로 흩어진 문제지에서는 그
   격자가 가짜 컬럼처럼 오인식됨. **수정**: `app/question_locator.py`의
   `_build_columns`를 "모든 줄을 먼저 뭉치고 그 안에서 앵커 찾기" → "앵커부터 전체에서
   찾고 그 위치로 컬럼을 정한 뒤 모든 줄을 배정" 방식으로 재설계. 줄 배정도 "최근접
   기준선"이 아니라 "내 x0 이하인 컬럼 중 가장 오른쪽 것"(구간 기반)으로 변경.
3. **원문자 보기 마커 OCR 오인식** — Clova가 `④`를 원문자 없이 그냥 숫자 `4`로 읽는
   경우가 있어서 보기 3·4번이 합쳐짐. **수정**: `pipeline.py`의
   `_split_passage_and_options`가 원문자뿐 아니라 "공백으로 둘러싸인, 다음 순번으로
   예상되는 숫자"도 마커로 인정하도록 보완.
4. **`find_finger_tip`이 손 대신 다리/종아리를 손끝으로 오인식 (2026-09-09)** —
   `vision_processor.py`. 100장 실사진 라벨링 세트(8번 섹션)로 정확도를 실측하다가
   발견함. 종이를 무릎에 올려두고 촬영하면, 사진 하단에 드러난 종아리/손목 피부가
   손보다 면적이 커서 "면적이 가장 큰 살색 덩어리 = 손"이라는 기존 로직이 그쪽을
   손끝으로 잘못 골랐다 (100장 중 16장 영향, 예측 좌표가 항상 사진 맨 아래로 튀는
   동일 패턴). **수정 1**: 후보 중 elongation(장변/단변 비율)이 12를 넘는, 화면
   가장자리를 따라 생기는 얇고 넓은 노이즈 띠는 제외 (`_elongation`,
   `_MAX_PLAUSIBLE_FINGER_ELONGATION`). 처음엔 "노이즈가 가늘고 기니 가장 elongation
   높은 걸 고르자"고 반대로 가정했다가 실측하고서 뒤집었음 - 실제 손 후보는 오히려
   뭉툭함(elongation 1.7~4.7), 문제의 노이즈 띠 쪽이 훨씬 가늘고 길었음(13~24).
   **수정 2**: 맨살 종아리처럼 elongation도 손과 비슷한 잔여 케이스를 위해, 후보
   점수에 "위쪽에 있을수록 유리한" 위치 가중치를 추가(`_select_finger_blob`의
   `position_weight`, 계수 1.3 - 사람이 무릎 위 종이를 내려다보며 찍으면 손이 항상
   종아리보다 카메라에 가까운/위쪽에 있다는 전제, 100장으로 실측해서 계수를 정함:
   1.0은 부족, 1.6은 다른 2건을 새로 깨뜨림, 1.3이 회귀 0건으로 최적). **결과**:
   P1 100px 이내 정답률 79%→93%, P3(문항 특정, predicted 손끝 기준) 80%→87%.
   **남은 한계**: 이 두 수정으로도 안 잡히는 케이스가 소수 남아있음 - 반지가 손끝이
   아닌 다른 손가락에 있어도 형태학적 연산(15×15 CLOSE)으로 손가락 덩어리가 붙어버려
   끝점이 반지 쪽으로 쏠리는 경우, 손끝이 손톱 위가 아니라 마디 쪽에 찍히는 경우 등.

---

## 6. 대기 중인 것

- **유사문제 풀어보기용 question/options 분리** — 프론트에 "유사문제 풀어보기"(사용자가
  답 고르고 채점받는 새 페이지) 기능이 추가될 예정. 지금 `similar_questions[].text`는
  지문+보기가 한 줄글로 뭉쳐 나와서(예: `"...것은? \nKate is good at skating...
  \n① are || ② does || ③ isn't || ④ don't"`) 화면에서 답을 고르게 만들기 어렵다.
  **Pinecone 데이터 담당자가 인덱스 자체를 분리된 필드로 재업로드해주기로 함** —
  백엔드에서 지금 파싱 코드를 만들지 않고 대기 중(2026-08-26 결정). 데이터가 바뀌면
  `pipeline.py`의 `_format_similar_questions()`를 새 필드명에 맞게 고치면 됨.

## 7. 알려진 한계

- **Pinecone 인덱스에 이미지 없음** — 원본 명세서엔 "인덱스에 이미지 포함"이라고
  적혀있었으나 틀린 정보였음. 실제 메타데이터 키는 `answer, category_large,
  category_mid, exam_round, exam_type, explanation, original_id, question_number,
  subject, text, year`뿐이고 순수 텍스트만 있다. 그래서 "유사문제 풀어보기"는 텍스트로만
  보여줄 수 있다. 실제 문제 사진까지 보여주려면 `data_pinecone`(데이터 구축 파이프라인)
  쪽에서 이미지를 인덱스에 새로 추가해야 함 — 백엔드에서 할 수 있는 일이 아님.
- **수학 미지원** — `subject_router`가 "수학"으로 판정하면 `unsupported_subject`만
  반환. 해설 생성기 자체가 없음.
- **`locate_confidence: "low"`인 경우 정확도 하락 가능** — 손끝이 애매한 위치(문항
  경계 등)일 때. 실사용 중 이 값이 자주 뜨면 `question_locator`의 밴드 판정을 더
  다듬어야 함.
- **Gemini가 가끔 깨진 JSON을 반환** — `pipeline.py`가 예외를 잡아서
  `{"status":"error"}`로 안전하게 처리하지만(500 안 남), 사용자 입장에선 그냥 실패로
  보임. 재시도 로직은 없음(무료 할당량 보호 우선).
- **회전된 사진 중 EXIF 태그 자체가 없는 경우** — `exif_transpose`는 EXIF 태그가 있을
  때만 보정한다. 태그 자체가 없는데 실제로 옆으로 찍힌 사진까지는 못 잡음.
- **P7(TTS) 미착수** — 음성 모델 확정 대기.

---

## 8. 정확도 검증 도구 (`정확도검증test/`, 리포지토리 루트, backend/ 밖)

2026-09-09 세션에 만든, 실제 100장 사진으로 P1/P3 정확도를 재는 도구 모음. `backend/`가
아니라 리포지토리 루트의 `정확도검증test/`에 있음 (git 추적 여부는 세션 종료 시점에
확정 안 됐을 수 있음 - `git status`로 확인할 것).

- `testimage/` — 실제 촬영 사진 100장, `annotations.json` — 사람이 직접 라벨링한
  정답(`annotate.py`로 만듦: 손끝 좌표 `x,y` + 문항 바운딩박스 `bbox` + 정답 문항번호
  `question_num`). **좌표계 주의**: `annotate.py`는 `cv2.imdecode`로 이미지를 읽는데,
  이게 기본 옵션으로 이미 EXIF orientation을 자동 보정한다(PIL `exif_transpose`
  결과와 픽셀 단위로 동일함을 실측 확인함) — 그래서 라벨 좌표에 별도 회전 변환을
  적용하면 안 되고, 리사이즈 배율만 곱하면 파이프라인 좌표계와 맞는다
  (`run_accuracy_eval.py`의 `gt_to_pipeline_space` 참고, 처음엔 이걸 반대로 가정해서
  한 번 틀렸었음).
- `run_accuracy_eval.py` — 실제 파이프라인 함수(`find_finger_tip`,
  `locate_question`)를 100장에 돌려서 P1(손끝 검출)/P3(문항 특정) 정확도를 실측.
  Clova 응답을 `clova_cache/`에 캐싱해서(이미지당 1회) 재실행해도 API를 다시 안
  부름 — **`--cache-only` 플래그를 쓰면 캐시에 없는 이미지는 Clova를 호출하지 않고
  건너뛴다** (Clova가 월 단위 호출 한도가 있어서, `vision_processor.py`만 고치고
  P3까지 재검증할 때는 이 플래그로 무료 재검증 가능 - P1은 애초에 Clova 없이도
  재검증 가능, `retest_p1_only.py` 참고).
- `retest_p1_only.py` — `find_finger_tip`만 다시 돌려서 P1 오차를 비교하는 스크립트
  (Clova 완전히 안 씀, 코드 수정→즉시 재검증 반복에 씀).
- `visualize_p1_failures.py`, `visualize_p1_after_fix.py` — 오차가 큰 이미지들을
  GT(초록)/predicted(분홍) 손끝을 같이 그린 크롭을 격자로 모아 보여주는 디버그
  스크립트 (Clova 안 씀). **이 시각화로 실제 실패 패턴을 눈으로 확인하고서야 원인을
  제대로 파악할 수 있었음** - 원인 가설을 코드만 보고 세우지 말고, 필요하면 이런
  시각화부터 만들 것.
- **P1 "정답" 판정 기준은 100px 반경(1960px 리사이즈 기준)** — 라벨링한 GT 좌표가
  손톱 위 한 점일 뿐이라 픽셀 단위로 정확히 일치할 필요는 없다는 사용자 판단으로
  도입. 실제 사진에 100px 원을 그려서 눈으로 확인한 값(손톱 하나보다 살짝 넉넉한
  크기). `run_accuracy_eval.py`/`retest_p1_only.py`의 `P1_HIT_THRESHOLD_PX`.
- **최신 정확도 (2026-09-09, 5번 섹션 4항 수정 반영 후)**: P1 100px 이내 93%,
  P3(predicted 손끝, 실제 프로덕션과 동일) 87%, P3(GT 손끝, question_locator 자체
  성능) 94%. 결과 파일은 `results/accuracy_metrics.txt`(요약)와
  `results/accuracy_raw_results.json`(100장 개별 결과, 재분석용)에 있음.
- **아직 없는 것**: `question_locator`가 그리는 빨간 박스 자체가 GT 바운딩박스와
  얼마나 겹치는지(IoU) 재는 지표는 아직 없음 - 지금은 "문항 번호가 맞았는지"만
  본다. 필요해지면 `locate_result.box`(현재 저장 안 함, `evaluate_one`에서 계산은
  됨)와 `gt_box_pipeline_space`(이미 저장됨)로 추가 가능.

---

## 9. 참고 문서

- `backend/README.md` (GitHub 클론 쪽에만 있음, 이 폴더엔 없을 수 있음) — 팀 공유용
  아키텍처 문서, 이 문서와 내용 겹침.
- 원본 명세서: `야학_파이프라인v2_명세서.md`, `클로드코드_프롬프트_모음.md`
  (P1~P8 각 단계의 상세 요구사항·완료조건이 적혀있던 문서. 사용자가 대화 중 직접
  붙여넣어 준 것이라 파일로는 없을 수 있음 — 필요하면 사용자에게 다시 요청할 것).
