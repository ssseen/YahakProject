"""
속도 측정 스크립트 (2026-10-26, 교수 미팅 4번 "속도" 3단계).

실제 앱과 같은 순서로 서버 API를 부른다 (FastAPI TestClient로 main.app을 같은 프로세스에서
호출 - 서버를 따로 띄울 필요 없음, 네트워크 시간은 빠짐):
  ① POST /api/analyze (checkOnly=true)  -> 사진 검사 (+ 서버가 sessionId 발급, 해설 앞단계 미리 처리 시작)
  ③ POST /api/analyze (sessionId + 질문, 사진 없음) -> 해설 (①이 retake면 여기서 끝)
     --legacy면 예전 방식(사진 다시 업로드 + checkResult)
녹음 시간 동안 서버가 미리 처리하는 걸 재현하려고 ① 뒤에 --record-sec초(기본 5) 기다린다
(녹음 파일이 있으면 STT 호출 시간이 더해짐).
  ② POST <STT 서버>/transcribe          -> 음성 인식 (audio/ 폴더에 녹음 파일이 있을 때만)
②는 실제 배포된 STT 서버(Cloud Run)를 부른다 - 앱도 그 서버를 쓰기 때문(네트워크 포함).
녹음 파일은 사진마다 audio/의 파일을 이름순으로 돌려가며 쓰고, 인식된 문장을 ③의 질문으로
넣는다. 녹음 파일이 없으면 ②를 건너뛰고 --question 고정 문장을 쓴다.

서버 응답의 "timings"(main.py/pipeline.py가 채움)를 한 줄씩 CSV에 쌓고, 끝나면 폴더별 평균을
출력한다. Clova/Pinecone/Gemini를 실제로 호출한다(사진 1장당 Clova 1회, Gemini 1회 정도).

사진 폴더 구조 - 하위 폴더 이름이 그대로 분류(category)가 된다:
  speedtest/image/guksagwa, eng, math (손끝 있음),
  hand_one (손끝 없음 + 문제 하나), hand_any (손끝 없음 + 문제 여러 개)

결과는 이 폴더(speedtest/)에 저장된다: speedtest_<시각>.csv(한 장당 한 줄) + 같은 이름의 .log
(서버 로그 전체). 사용법 (speedtest/에서, 파이썬은 backend의 venv):
  ../backend/venv/Scripts/python speed_test.py               # image/ 전체, 1회씩
  ../backend/venv/Scripts/python speed_test.py --repeat 2    # 같은 사진 2번씩
  ../backend/venv/Scripts/python speed_test.py --out speedtest_x.csv --resume
      (중간에 끊겼을 때: 같은 CSV에 이미 있는 (사진, 회차)는 건너뛰고, 로그는 이어 씀)
"""
import argparse
import base64
import csv
import io
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND_DIR = HERE.parent / "backend"
START_DIR = Path.cwd()  # 인자로 받은 상대경로(--out 등)는 실행한 폴더 기준으로 해석한다
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)  # backend 코드가 .env 등을 현재 폴더 기준으로 찾는 경우 대비

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

_EXTS = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
_AUDIO_EXTS = {".webm", ".m4a", ".mp3", ".wav", ".ogg", ".aac", ".mp4"}
_STT_URL = "https://yahak-stt-815747505478.asia-northeast3.run.app"

# ① 응답 timings -> check_ 접두사, ③ 응답 timings -> 그대로
_CHECK_KEYS = ["analyze_image", "resize", "clova", "clova_calls", "upright", "single_question",
               "server_total"]
_ANALYZE_KEYS = ["resize", "finger_redetect", "clova", "clova_calls", "upright", "single_question",
                 "locate", "pinecone", "type_classifier", "box", "gemini", "explain_total",
                 "pipeline_total", "save_json", "server_total"]
_COLUMNS = (
    ["category", "file", "repeat", "check_status", "check_client_s"]
    + [f"check_{k}" for k in _CHECK_KEYS]
    + ["audio_file", "stt_s", "stt_text", "stt_error"]
    + ["status", "reason", "branch", "finger_detected", "ocr_cache_hit", "analyze_client_s",
       "prepare_total", "prepare_wait", "similar"]
    + _ANALYZE_KEYS
    + ["gemini_calls_n", "prompt_tokens", "output_tokens", "thinking_tokens", "diagram_seconds",
       "after_voice_s", "total_wait_s", "error"]
)


def _data_uri(path):
    mime = _EXTS[path.suffix.lower()]
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def _post(client, payload):
    t0 = time.perf_counter()
    res = client.post("/api/analyze", json=payload)
    elapsed = round(time.perf_counter() - t0, 3)
    try:
        data = res.json()
    except ValueError:
        data = {"status": "error", "message": res.text}
    if res.status_code != 200:
        data = {"status": "error", "message": f"HTTP {res.status_code}: {data}"}
    return data, elapsed


def _transcribe(stt_url, audio_path):
    import httpx
    t0 = time.perf_counter()
    try:
        res = httpx.post(stt_url + "/transcribe", timeout=180,
                         files={"audio_file": (audio_path.name, audio_path.read_bytes())})
        res.raise_for_status()
        return (res.json().get("text") or "").strip(), round(time.perf_counter() - t0, 3), None
    except Exception as e:
        return "", round(time.perf_counter() - t0, 3), repr(e)[:200]


def run_one(client, path, category, repeat, question, audio_path=None, stt_url=None,
            record_sec=5.0, legacy=False):
    row = {"category": category, "file": path.name, "repeat": repeat}
    data_uri = _data_uri(path)

    check, check_s = _post(client, {"image": data_uri, "checkOnly": True})
    row["check_status"] = check.get("status")
    row["check_client_s"] = check_s
    for k in _CHECK_KEYS:
        row[f"check_{k}"] = (check.get("timings") or {}).get(k)
    row["total_wait_s"] = check_s

    if check.get("status") != "checked":
        row["reason"] = check.get("reason")
        row["error"] = check.get("message") if check.get("status") == "error" else None
        return row

    time.sleep(record_sec)  # 사용자가 질문을 말하는 시간 (서버는 이 동안 미리 처리)
    stt_s = 0.0
    if audio_path is not None:
        text, stt_s, stt_err = _transcribe(stt_url, audio_path)
        row.update({"audio_file": audio_path.name, "stt_s": stt_s, "stt_text": text, "stt_error": stt_err})
        print(f"② 음성 인식 {stt_s}초: {text!r} {stt_err or ''}")
        if text:
            question = text  # 앱과 같이 인식된 문장을 질문으로 (실패하면 고정 문장으로 계속)

    check_result = {"finger_detected": check["finger_detected"], "x": check.get("x"), "y": check.get("y")}
    if legacy or not check.get("sessionId"):
        payload = {"image": data_uri, "userQuestion": question, "checkResult": check_result}
    else:
        payload = {"sessionId": check["sessionId"], "userQuestion": question}
    result, analyze_s = _post(client, payload)
    t = result.get("timings") or {}
    row.update({
        "status": result.get("status"),
        "reason": result.get("reason"),
        "branch": result.get("branch"),
        "finger_detected": check["finger_detected"],
        "ocr_cache_hit": t.get("ocr_cache_hit"),
        "analyze_client_s": analyze_s,
        "after_voice_s": round(stt_s + analyze_s, 3),
        "total_wait_s": round(check_s + stt_s + analyze_s, 3),
        "error": result.get("message") if result.get("status") == "error" else None,
    })
    for k in _ANALYZE_KEYS + ["prepare_total", "prepare_wait", "similar"]:
        row[k] = t.get(k)

    calls = t.get("gemini_calls") or []
    row["gemini_calls_n"] = len(calls)
    for k in ("prompt_tokens", "output_tokens", "thinking_tokens", "diagram_seconds"):
        vals = [c.get(k) for c in calls if c.get(k) is not None]
        row[k] = sum(vals) if vals else None
    return row


def _mean(rows, key):
    vals = [float(r[key]) for r in rows if r.get(key) not in (None, "")]
    return sum(vals) / len(vals) if vals else None


def print_summary(rows):
    """폴더별 평균. 단계 시간은 ③ 기준(손끝없음_여러문제는 ①에서 끝나므로 ① 기준)."""
    stages = ["resize", "finger_redetect", "clova", "upright", "locate", "pinecone",
              "type_classifier", "box", "gemini", "explain_total", "server_total"]
    print("\n===== 폴더별 평균 (초) =====")
    for cat in sorted({r["category"] for r in rows}):
        cr = [r for r in rows if r["category"] == cat]
        ok = [r for r in cr if r.get("status") == "success"]
        print(f"\n[{cat}] {len(cr)}회 (③ 성공 {len(ok)}회)")
        line = f"  ① 촬영 검사: 사용자 대기 {_fmt(_mean(cr, 'check_client_s'))}"
        for k in ("check_analyze_image", "check_resize", "check_clova", "check_upright"):
            m = _mean(cr, k)
            if m is not None:
                line += f" | {k[6:]} {_fmt(m)}"
        print(line)
        if not ok:
            continue
        if _mean(ok, "stt_s") is not None:
            print(f"  ② 음성 인식: {_fmt(_mean(ok, 'stt_s'))}")
        session = _mean(ok, "prepare_wait") is not None
        total = _mean(ok, "server_total")
        if session:
            # 세션 방식: resize~box는 녹음 중에 미리 처리됨 - ③ 시간 대비 비율은 의미 없음
            print(f"  (녹음 중 미리 처리 {_fmt(_mean(ok, 'prepare_total'))} - 아래 resize~box)")
        print(f"  ③ 해설 요청: 사용자 대기 {_fmt(_mean(ok, 'analyze_client_s'))}"
              + (f" | 미리 처리 끝나길 기다림 {_fmt(_mean(ok, 'prepare_wait'))}" if session else ""))
        for k in stages:
            m = _mean(ok, k)
            if m is None:
                continue
            share = f" ({m / total * 100:4.1f}%)" if total and not session and k != "server_total" else ""
            print(f"     {k:<16}{_fmt(m)}{share}")
        print(f"  Gemini 토큰 평균: 입력 {_fmt(_mean(ok, 'prompt_tokens'), 0)} / "
              f"출력 {_fmt(_mean(ok, 'output_tokens'), 0)} / "
              f"생각 {_fmt(_mean(ok, 'thinking_tokens'), 0)}")
        if _mean(ok, "stt_s") is not None:
            print(f"  말이 끝난 뒤 대기(②+③) {_fmt(_mean(ok, 'after_voice_s'))}")
        print(f"  전체 대기(①+②+③) {_fmt(_mean(ok, 'total_wait_s'))}")


def _fmt(v, nd=2):
    return "-" if v is None else f"{v:.{nd}f}"


class _Tee(io.TextIOBase):
    """화면 출력과 로그 파일에 동시에 쓴다 (서버 print 로그까지 전부 .log에 남기려고)."""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, s):
        for st in self.streams:
            st.write(s)
            st.flush()
        return len(s)

    def flush(self):
        for st in self.streams:
            st.flush()


def main_cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=str(HERE / "image"))
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--question", default="이 문제 좀 알려줘")
    ap.add_argument("--audio-dir", default=str(HERE / "audio"))
    ap.add_argument("--stt-url", default=_STT_URL)
    ap.add_argument("--record-sec", type=float, default=5.0, help="① 뒤 녹음 시간 흉내(초)")
    ap.add_argument("--legacy", action="store_true", help="예전 방식(③에 사진 다시 업로드)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--sleep", type=float, default=0.0, help="사진 사이 대기(초) - API 한도 대비")
    args = ap.parse_args()

    root = START_DIR / args.root
    images = sorted(p for p in root.rglob("*") if p.suffix.lower() in _EXTS)
    if not images:
        sys.exit(f"사진이 없음: {root}")

    out = START_DIR / args.out if args.out else HERE / f"speedtest_{time.strftime('%Y%m%d_%H%M%S')}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    for st in (sys.__stdout__, sys.__stderr__):  # 윈도우 콘솔(cp949)에서 못 찍는 문자가 있어도 안 죽게
        try:
            st.reconfigure(errors="replace")
        except AttributeError:
            pass
    log_file = open(out.with_suffix(".log"), "a", encoding="utf-8")
    sys.stdout = _Tee(sys.__stdout__, log_file)
    sys.stderr = _Tee(sys.__stderr__, log_file)
    print(f"\n===== 시작 {time.strftime('%Y-%m-%d %H:%M:%S')} / 사진 {len(images)}장 x {args.repeat}회 =====")
    done, rows = set(), []
    if args.resume and out.exists():
        with open(out, encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        done = {(r["category"], r["file"], str(r["repeat"])) for r in rows}
        print(f"이어하기: {len(done)}건 건너뜀")

    audio_dir = START_DIR / args.audio_dir
    audios = sorted(p for p in audio_dir.glob("*") if p.suffix.lower() in _AUDIO_EXTS) if audio_dir.exists() else []
    if audios:
        # STT 서버가 꺼져 있으면(min-instances 0) 첫 요청에 모델 로딩으로 수십 초 걸린다 - 그건 따로 재고 깨워둔다
        import httpx
        t0 = time.perf_counter()
        try:
            httpx.get(args.stt_url + "/health", timeout=180)
        except Exception as e:
            print(f"STT 서버 health 실패: {e!r}")
        print(f"STT 서버 깨우기(/health) {time.perf_counter() - t0:.1f}초 - 30초 넘으면 꺼져 있다가 켜진 것(콜드 스타트)")
        print(f"녹음 파일 {len(audios)}개: {[p.name for p in audios]}")
    else:
        print(f"녹음 파일 없음({audio_dir}) - ② 건너뛰고 고정 질문 {args.question!r} 사용")

    # Pinecone 첫 검색은 연결 준비로 느리다 - 서버(lifespan)처럼 미리 연결해두고 측정한다
    import pipeline
    pipeline.warmup_pinecone()

    client = TestClient(main.app)  # with 블록 없이 -> lifespan(STT 모델 로딩) 안 돌림
    new_file = not out.exists()
    with open(out, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_COLUMNS, extrasaction="ignore")
        if new_file:
            writer.writeheader()
        jobs = [(p, rep) for rep in range(1, args.repeat + 1) for p in images]
        for i, (path, rep) in enumerate(jobs, 1):
            category = path.parent.name
            if (category, path.name, str(rep)) in done:
                continue
            print(f"\n######## [{i}/{len(jobs)}] {category}/{path.name} (회차 {rep}) ########")
            try:
                audio = audios[(i - 1) % len(audios)] if audios else None
                row = run_one(client, path, category, rep, args.question, audio, args.stt_url,
                              args.record_sec, args.legacy)
            except Exception as e:  # 한 장 실패로 전체가 멈추지 않게
                row = {"category": category, "file": path.name, "repeat": rep, "error": repr(e)}
            writer.writerow(row)
            f.flush()
            rows.append(row)
            print(f">>> {row.get('check_status')} -> {row.get('status')} "
                  f"대기 {row.get('total_wait_s')}초 {row.get('error') or ''}")
            if args.sleep:
                time.sleep(args.sleep)

    print_summary(rows)
    print(f"\nCSV: {out}")


if __name__ == "__main__":
    main_cli()
