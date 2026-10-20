"""
같은 학력(초졸/중졸/고졸) 이웃만 사용했을 때 top-1 정확도 비교
(search_cache.json만 읽음. API 호출 없음, .env 불필요)

사용법 (search_cache.json이 있는 폴더에서):
  python same_level.py
"""
import json
from collections import Counter, defaultdict

CACHE_PATH = "search_cache.json"


def level(id_str):
    return str(id_str).split("_")[0]          # 예: '고졸_2026_2회_사회_18' -> '고졸'


with open(CACHE_PATH, encoding="utf-8") as f:
    rows = json.load(f)

levels = Counter(level(r["id"]) for r in rows)
print("테스트 학력 분포:", dict(levels))
nb_levels = Counter(level(h["orig_id"]) for r in rows for h in r["filtered"] if h.get("orig_id"))
print("이웃 학력 분포 :", dict(nb_levels), "\n")

res = {
    "기존 top-1 (학력 무관)": [0, 0, 0],
    "같은 학력 이웃만 (없으면 기존 top-1)": [0, 0, 0],
    "같은 학력 이웃만 (없으면 오답)": [0, 0, 0],
}                                                # [문항, 대분류 정답, 중분류 정답]
no_same = 0
by_level = defaultdict(lambda: {"base": [0, 0], "same": [0, 0], "n": 0})

for r in rows:
    hits = sorted(r["filtered"], key=lambda h: -h["score"])
    if not hits:
        continue
    lv = level(r["id"])
    base = hits[0]
    same = [h for h in hits if level(h.get("orig_id", "")) == lv]
    pick = same[0] if same else None
    if not same:
        no_same += 1

    def upd(key, h):
        res[key][0] += 1
        if h is not None:
            res[key][1] += h["large"] == r["true_large"]
            res[key][2] += h["mid"] == r["true_mid"]

    upd("기존 top-1 (학력 무관)", base)
    upd("같은 학력 이웃만 (없으면 기존 top-1)", pick or base)
    upd("같은 학력 이웃만 (없으면 오답)", pick)

    b = by_level[lv]
    b["n"] += 1
    b["base"][0] += base["large"] == r["true_large"]
    b["same"][0] += (pick or base)["large"] == r["true_large"]

print(f"{'방식':<36}{'대분류':>9}{'중분류':>9}")
for k, (n, l, m) in res.items():
    print(f"{k:<36}{l / n * 100:>8.1f}%{m / n * 100:>8.1f}%")
print(f"\n같은 학력 이웃이 top-10 안에 하나도 없던 문제: {no_same}건 / {len(rows)}문제")

print("\n=== 학력별 대분류 정확도 (기존 → 같은 학력 이웃, 없으면 기존) ===")
for lv, b in by_level.items():
    print(f"{lv}  {b['n']}문제  {b['base'][0] / b['n'] * 100:.1f}% → {b['same'][0] / b['n'] * 100:.1f}%")
print("\n주의: 이웃은 과목 필터 O의 top-10 안에서만 골랐어. top-10이 다른 학력으로 채워진 문제는 '없음'으로 셌어.")