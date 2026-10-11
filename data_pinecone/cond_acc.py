"""
top-1 기준 조건부 중분류 정확도 + 상위 3개 후보 안에 정답이 있는 비율
(search_cache.json만 읽음. API 호출 없음, .env 불필요)

사용법 (search_cache.json이 있는 폴더에서):
  python cond_acc.py
"""
import csv
import json
from collections import Counter

CACHE_PATH = "search_cache.json"
OUT_PATH = "large_ok_mid_wrong.csv"

with open(CACHE_PATH, encoding="utf-8") as f:
    rows = json.load(f)

n = large_ok = mid_ok = both_ok = 0
top3_large = top3_mid = 0
mid_pairs = Counter()
wrong = [["id", "subject", "true_large", "true_mid", "top1_mid", "top1_score", "test_question"]]

for r in rows:
    hits = sorted(r["filtered"], key=lambda h: -h["score"])
    if not hits:
        continue
    n += 1
    t = hits[0]
    l_ok = t["large"] == r["true_large"]
    m_ok = t["mid"] == r["true_mid"]
    large_ok += l_ok
    mid_ok += m_ok
    both_ok += (l_ok and m_ok)
    top3_large += any(h["large"] == r["true_large"] for h in hits[:3])
    top3_mid += any(h["mid"] == r["true_mid"] for h in hits[:3])
    if l_ok and not m_ok:
        mid_pairs[(r["subject"], r["true_large"], r["true_mid"], t["mid"])] += 1
        wrong.append([r["id"], r["subject"], r["true_large"], r["true_mid"], t["mid"],
                      f"{t['score']:.3f}", (r.get("text", "") or "").replace("\n", " ")])

pct = lambda a, b: f"{a / b * 100:.1f}%" if b else "-"

print(f"전체 {n}문제 (top-1, subject 필터 O)\n")
print(f"대분류 정확도           : {large_ok}/{n} = {pct(large_ok, n)}")
print(f"중분류 정확도 (전체)    : {mid_ok}/{n} = {pct(mid_ok, n)}   ← PPT에 쓰는 값")
print(f"대분류·중분류 둘 다 정답: {both_ok}/{n} = {pct(both_ok, n)}")
print(f"조건부 중분류 정확도    : {both_ok}/{large_ok} = {pct(both_ok, large_ok)}   (대분류를 맞힌 문제 중 중분류도 맞은 비율)")
print(f"대분류 오답 {n - large_ok}건 / 대분류는 맞고 중분류만 틀림 {large_ok - both_ok}건\n")

print("[참고] 상위 3개 후보 안에 정답이 있는 비율")
print(f"  대분류: {pct(top3_large, n)}   중분류: {pct(top3_mid, n)}\n")

print("=== 대분류는 맞고 중분류만 틀린 쌍 상위 10 (과목 / 대분류 / 정답 중분류 → 예측 중분류) ===")
for (s, L, a, b), c in mid_pairs.most_common(10):
    print(f"{c:>3}건  {s} / {L} / {a} → {b}")

with open(OUT_PATH, "w", newline="", encoding="utf-8-sig") as f:
    csv.writer(f).writerows(wrong)
print(f"\n목록 → {OUT_PATH}")