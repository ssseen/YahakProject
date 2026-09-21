import os
from dotenv import load_dotenv
load_dotenv()

from pinecone import Pinecone
import json

PINECONE_API_KEY = os.environ["PINECONE_API_KEY"]
INDEX_NAME = "geondi-questions"
NAMESPACE  = "questions"

pc = Pinecone(api_key=PINECONE_API_KEY)
index = pc.Index(INDEX_NAME)

result = index.search_records(
    namespace=NAMESPACE,
    query={"inputs": {"text": "다음 중 사람 눈의 구조에서 망막이 받아들이는 자극은?"}, "top_k": 3},
)

print(json.dumps(result, indent=2, default=str, ensure_ascii=False))