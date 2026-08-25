"""
Pinecone 인덱스를 평가셋으로 사용한 과목 분류(BRANCH_OF) 정확도 측정.
leave-one-out: 각 문항 자신의 text로 검색해서, 자기 자신을 제외한 상위 10건의
subject 다수결이 실제 subject(를 BRANCH_OF로 변환한 값)와 얼마나 일치하는지 잰다.
Gemini 호출 없음. 인덱스는 읽기 전용으로만 사용한다 (업서트/수정 없음).
"""
import os
import sys
import time
from collections import Counter, defaultdict

from dotenv import load_dotenv
from pinecone import Pinecone

load_dotenv()

INDEX_NAME = "geondi-questions"
NAMESPACE = "questions"
THRESHOLDS = [0.25, 0.30, 0.35, 0.40, 0.45]

BRANCH_OF = {
    "영어": "영어", "수학": "수학",
    "국어": "국사과", "사회": "국사과", "과학": "국사과",
    "한국사": "국사과", "도덕": "국사과",
}
BRANCHES = ["영어", "수학", "국사과"]


def get_index():
    api_key = os.getenv("PINECONE_API_KEY")
    if not api_key:
        print("PINECONE_API_KEY가 .env에 없음")
        sys.exit(1)
    return Pinecone(api_key=api_key).Index(INDEX_NAME)


def fetch_all_questions(index):
    """
    전체 문항 조회 방법: index.list(namespace=...)가 네임스페이스 안의 벡터 id를
    페이지 단위(Iterator[ListResponse])로 돌려준다. 전부 순회해 id를 모은 뒤,
    index.fetch(ids=[...100개씩...])로 metadata(subject/text 등)를 받아온다.
    (설치된 pinecone SDK: pinecone.index.Index, 9.x 계열. search()의 통합
    임베딩과 달리 fetch()는 저장된 값·메타데이터를 그대로 반환한다.)
    """
    all_ids = []
    for page in index.list(namespace=NAMESPACE):
        all_ids.extend(v.id for v in page)

    questions = []
    batch = 100
    for i in range(0, len(all_ids), batch):
        chunk = all_ids[i:i + batch]
        resp = index.fetch(ids=chunk, namespace=NAMESPACE)
        for vid, vec in resp.vectors.items():
            md = vec.metadata or {}
            questions.append({
                "id": vid,
                "subject": md.get("subject"),
                "text": md.get("text", ""),
            })
    return questions


def hit_score(h):
    # .score 프로퍼티 사용. _score 아님 (기존 버그 재발 방지).
    return getattr(h, "score", None)


def hit_id(h):
    return getattr(h, "id", None)


def hit_subject(h):
    fields = getattr(h, "fields", None) or {}
    return fields.get("subject")


def search_neighbors(index, text):
    res = index.search(namespace=NAMESPACE, query={"inputs": {"text": text}, "top_k": 11})
    result = getattr(res, "result", res)
    hits = getattr(result, "hits", None)
    if hits is None and isinstance(result, dict):
        hits = result.get("hits")
    return list(hits or [])


def main():
    index = get_index()

    print("전체 문항 조회 중...")
    questions = fetch_all_questions(index)
    print(f"총 {len(questions)}건")

    subject_counts = Counter(q["subject"] for q in questions)
    print("\n[인덱스 내 subject 값 분포]")
    for subj, cnt in subject_counts.most_common():
        print(f"  {subj!r}: {cnt}")

    unknown = [q for q in questions if q["subject"] not in BRANCH_OF]
    if unknown:
        print(f"\n경고: BRANCH_OF에 없는 subject {len(unknown)}건 (평가에서 제외)")

    print("\nleave-one-out 검색 시작 (문항마다 top_k=11 1회, 5개 임계값에 재사용)...")
    records = []
    t0 = time.time()
    skipped_no_text = 0
    search_failed = 0
    for i, q in enumerate(questions):
        if q["subject"] not in BRANCH_OF:
            continue
        if not q["text"]:
            skipped_no_text += 1
            continue
        try:
            hits = search_neighbors(index, q["text"])
        except Exception as e:
            print(f"  검색 실패 id={q['id']}: {e!r}")
            search_failed += 1
            continue
        neighbors = [h for h in hits if hit_id(h) != q["id"]][:10]
        records.append((q, neighbors))
        if (i + 1) % 200 == 0:
            elapsed = time.time() - t0
            print(f"  {i + 1}/{len(questions)} 처리, 경과 {elapsed:.1f}초")

    print(f"\n검색 완료: {len(records)}건 평가 대상, text 없어 건너뜀 {skipped_no_text}건, "
          f"검색 실패 {search_failed}건, 총 소요 {time.time() - t0:.1f}초")

    for threshold in THRESHOLDS:
        correct = 0
        total = 0
        confusion = defaultdict(Counter)
        agreement_buckets = defaultdict(lambda: [0, 0])
        english_errors = []

        for q, neighbors in records:
            true_branch = BRANCH_OF[q["subject"]]
            votes = []
            for h in neighbors:
                s = hit_score(h)
                subj = hit_subject(h)
                if s is not None and s >= threshold and subj in BRANCH_OF:
                    votes.append(BRANCH_OF[subj])

            if votes:
                vc = Counter(votes)
                pred, n = vc.most_common(1)[0]
                agreement = n / len(votes)
            else:
                pred, agreement = "국사과", 0.0

            total += 1
            is_correct = pred == true_branch
            if is_correct:
                correct += 1
            confusion[true_branch][pred] += 1

            if agreement == 1.0:
                bucket = "1.0"
            elif agreement >= 0.8:
                bucket = "0.8~1.0"
            elif agreement >= 0.5:
                bucket = "0.5~0.8"
            else:
                bucket = "0.5 미만"
            agreement_buckets[bucket][0] += 1
            if is_correct:
                agreement_buckets[bucket][1] += 1

            if (true_branch == "영어") != (pred == "영어"):
                top3 = [(hit_subject(h), hit_score(h)) for h in neighbors[:3]]
                english_errors.append((q["id"], true_branch, pred, top3))

        print(f"\n=== THRESHOLD = {threshold} ===")
        if total:
            print(f"정확도: {correct}/{total} = {correct / total:.4f}")
        else:
            print("평가 대상 없음")

        print("Confusion matrix (실제 -> 예측)")
        header = "실제\\예측 " + "".join(f"{b:>10}" for b in BRANCHES)
        print(header)
        for tb in BRANCHES:
            row = f"{tb:>8} " + "".join(f"{confusion[tb][pb]:>10}" for pb in BRANCHES)
            print(row)

        print("Agreement 분포 (구간: 건수, 정확도)")
        for bucket in ["1.0", "0.8~1.0", "0.5~0.8", "0.5 미만"]:
            cnt, corr = agreement_buckets[bucket]
            acc = corr / cnt if cnt else 0.0
            print(f"  {bucket}: {cnt}건, 정확도 {acc:.4f}")

        print(f"영어 관련 오분류(영어인데 다른 과목으로, 또는 그 반대) {len(english_errors)}건")
        for qid, tb, pb, top3 in english_errors:
            print(f"  id={qid} 실제={tb} 예측={pb} top3={top3}")


if __name__ == "__main__":
    main()
