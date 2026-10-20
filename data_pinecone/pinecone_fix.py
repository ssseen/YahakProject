from pinecone_upsert import build_records, upsert_records

TARGET_IDS = {"중졸_2024_1회_영어_20", "중졸_2024_1회_영어_21"}

records = build_records()
targets = [r for r in records if r["original_id"] in TARGET_IDS]

if len(targets) != len(TARGET_IDS):
    raise SystemExit(f"대상 문제를 다 못 찾음: {[r['original_id'] for r in targets]}")

# 올리기 전에 선택지가 제대로 바뀌었는지 눈으로 확인
for r in targets:
    print(r["original_id"], "→", r["choices"][:50])

if input("이대로 올릴까? (y/n) ") == "y":
    upsert_records(targets)