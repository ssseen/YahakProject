# 손끝 좌표 휴먼 어노테이션 도구

사진 속 손끝 위치(점)와 문항 영역(바운딩박스)을 직접 클릭/드래그로 표시해서
`annotations.json`으로 저장하는 도구입니다.

## 1. 준비

1. Python 3.9 이상 설치되어 있어야 합니다.
2. 이 폴더(`annotation_tool`)를 통째로 받습니다.
3. 터미널에서 이 폴더로 이동한 뒤, **가상환경(venv)을 새로 만들고 그 안에서** 설치합니다.
   (시스템 파이썬에 바로 설치하면 다른 프로젝트 환경이 꼬일 수 있어서 꼭 venv를 씁니다.)

```bash
# 폴더로 이동
cd annotation_tool

# 가상환경 생성
python -m venv venv

# 가상환경 켜기 (Windows)
venv\Scripts\activate
# 가상환경 켜기 (Mac/Linux)
source venv/bin/activate

# 필요한 패키지 설치
pip install -r requirements.txt
```

## 2. 사진 넣기

`annotation_tool/testimage` 폴더 안에 라벨링할 jpg 사진들을 넣습니다.
(파일명은 상관없이 `.jpg` 확장자면 됩니다.)

## 3. 실행

```bash
python annotate.py
```

## 4. 사용 방법

이미지 한 장마다 순서대로 진행됩니다.

1. **좌클릭**: 손끝 위치 클릭 → 녹색 점으로 표시됨
2. 클릭하면 터미널(콘솔)에 `문항번호를 입력하세요` 라고 나옴 → 숫자 입력 후 Enter
3. **마우스 드래그**: 문제 영역을 사각형으로 드래그 → 빨간 사각형으로 표시됨
4. **Enter**: 현재 이미지 확정하고 다음 이미지로 이동

### 단축키
- `r` : 현재 단계(점 또는 박스)를 다시 찍기
- `Enter` : 확정하고 다음 이미지로
- `ESC` : 중단 (그때까지 한 것은 저장된 상태로 유지됨)

### 참고
- 중간에 껐다가 다시 `python annotate.py` 실행하면, 이미 완료한 이미지는 자동으로 건너뛰고 이어서 진행됩니다.
- 결과는 이미지 한 장 끝날 때마다 바로 `annotations.json`에 저장됩니다.

## 5. 결과 보내주기

다 끝나면 `annotation_tool/annotations.json` 파일 하나만 보내주시면 됩니다.
형식은 아래처럼 이미지 파일명을 key로 해서 저장됩니다.

```json
{
  "example.jpg": {
    "x": 762,
    "y": 1313,
    "question_num": 2,
    "bbox": {
      "x_min": 753,
      "y_min": 1111,
      "x_max": 2670,
      "y_max": 2209
    }
  }
}
```
