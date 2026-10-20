"""
top-1 유사도 구간별 대분류 정확도 -> 오답 원인 가설 확인
(search_cache.json만 읽음. API 호출 없음, .env 불필요)

사용법 (search_cache.json이 있는 폴더에서):
  python cause_check.py
"""
import csv
import json
from collections import defaultdict

CACHE_PATH = "search_cache.json"
OUT_PATH = "errors_by_score.csv"

with open(CACHE_PATH, encoding="utf-8") as f:
    rows = json.load(f)

items = []
for r in rows:
    hits = sorted(r["filtered"], key=lambda h: -h["score"])
    if not hits:
        continue
    t = hits[0]
    items.append({
        "id": r["id"], "subject": r["subject"], "score": t["score"],
        "ok": t["large"] == r["true_large"],
        "true_large": r["true_large"], "top1_large": t["large"],
        "test_q": (r.get("text", "") or "").replace("\n", " "),
        "top1_q": (t.get("question", "") or "").replace("\n", " "),
    })

items.sort(key=lambda x: x["score"])
n = len(items)
bins = [("하위 1/3 (유사도 낮음)", items[: n // 3]),
        ("중간 1/3", items[n // 3: 2 * n // 3]),
        ("상위 1/3 (유사도 높음)", items[2 * n // 3:])]

print(f"전체 {n}문제 / 대분류 오답 {sum(not x['ok'] for x in items)}건\n")
print(f"{'top-1 유사도 구간':<24}{'점수 범위':>16}{'문항':>6}{'오답':>6}{'대분류 정확도':>14}")
for name, b in bins:
    wrong = sum(not x["ok"] for x in b)
    lo, hi = b[0]["score"], b[-1]["score"]
    print(f"{name:<24}{lo:>8.3f}~{hi:.3f}{len(b):>6}{wrong:>6}{(len(b) - wrong) / len(b) * 100:>13.1f}%")

print("\n=== 과목별 오답 평균 유사도 vs 정답 평균 유사도 ===")
by = defaultdict(lambda: {"ok": [], "bad": []})
for x in items:
    by[x["subject"]]["ok" if x["ok"] else "bad"].append(x["score"])
avg = lambda v: sum(v) / len(v) if v else 0
for s, d in by.items():
    print(f"{s:<6} 정답 {avg(d['ok']):.3f} ({len(d['ok'])}건) / 오답 {avg(d['bad']):.3f} ({len(d['bad'])}건)")

# 유사도 높은 순으로 정렬한 오답 목록 (직접 읽어보기용)
wrong = sorted([x for x in items if not x["ok"]], key=lambda x: -x["score"])
with open(OUT_PATH, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["id", "subject", "top1_score", "true_large", "top1_large", "test_question", "top1_question"])
    for x in wrong:
        w.writerow([x["id"], x["subject"], f"{x['score']:.3f}", x["true_large"], x["top1_large"], x["test_q"], x["top1_q"]])
print(f"\n오답 목록(유사도 높은 순) -> {OUT_PATH}")
print("해석: 하위 구간에서만 정확도가 크게 떨어지면 'DB 커버리지 부족', 상위 구간에도 오답이 많으면 '라벨 불일치/경계 모호' 쪽이야.")