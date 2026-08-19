import os
from dotenv import load_dotenv
load_dotenv()

from pinecone import Pinecone

# ── 설정 ──────────────────────────────────────────
PINECONE_API_KEY = os.environ["PINECONE_API_KEY"]
INDEX_NAME       = "geondi-questions"
NAMESPACE        = "questions"

pc = Pinecone(api_key=PINECONE_API_KEY)
index = pc.Index(INDEX_NAME)


def _try_get(obj, *keys, default=None):
    for k in keys:
        try:
            return obj[k]
        except (KeyError, TypeError):
            continue
    return default


def search(query_text, top_k=5, filter_dict=None):
    results = index.search(
        namespace=NAMESPACE,
        query={
            "inputs": {"text": query_text},
            "top_k": top_k,
        },
        filter=filter_dict,
    )

    hits = results["result"]["hits"]
    print(f"\n검색어: '{query_text}' (결과 {len(hits)}건)")
    print("=" * 60)

    for hit in hits:
        score = _try_get(hit, "_score", "score", default=0)
        hit_id = _try_get(hit, "_id", "id", default="")
        meta = _try_get(hit, "fields", default={})

        print(f"[유사도 {score:.3f}] id={hit_id} / original_id={meta.get('original_id', '')}")
        print(f"  과목: {meta.get('subject')} / 대분류: {meta.get('category_large')} / 중분류: {meta.get('category_mid')}")
        text_preview = meta.get("text", "")[:80]
        print(f"  문제: {text_preview}...")
        print()


if __name__ == "__main__":
    # ── 테스트 1: 필터 없이 자유 검색 ──
    search("이차방정식의 근의 공식을 이용해 방정식을 푸는 문제")

    # ── 테스트 2: 메타데이터 필터 걸어서 검색 ──
    search(
        "물질이 화학적으로 결합하는 원리",
        filter_dict={"subject": {"$eq": "과학"}}
    )