import os
import asyncio
from typing import List, Dict, Any
import redis.asyncio as redis
# from redisvl.index import SearchIndex
from redisvl.index import AsyncSearchIndex
from sentence_transformers import SentenceTransformer
from redisvl.query import VectorQuery
from redisvl.query.filter import Tag


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:8001")
SCHEMA_PATH = os.getenv("SCHEMA_PATH", "schema.yaml")
EMBED_MODEL_NAME = os.getenv("EMBED_MODEL_NAME", "sentence-transformers/all-MiniLM-L6-v2")

VECTOR_FIELD = "embedding" 
RETURN_FIELDS = ["patient_id", "kind", "text", "vector_distance"]


_model = None

async def get_redis():
    return redis.from_url(REDIS_URL, encoding="utf-8", decode_responses=False)

def get_embedder():
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBED_MODEL_NAME)
    return _model

def embed(texts: List[str]):
    model = get_embedder()
    return model.encode(texts, normalize_embeddings=True).astype("float32")

class PatientRAG:
    def __init__(self):
        # self.index = SearchIndex.from_yaml(SCHEMA_PATH) 
        self.index = AsyncSearchIndex.from_yaml(SCHEMA_PATH)

        # RedisVL handles index creation / existence
    async def init(self, r: redis.Redis):
        await self.index.connect(redis_url=REDIS_URL)

        if not await self.index.exists():
            await self.index.create(overwrite=True)

    async def upsert_docs(self, r: redis.Redis, docs: List[Dict[str, Any]]):
        """
        docs: [{'id': 'postop:doc:<uuid>', 'patient_id':'p1','kind':'meds','text':'...'}]
        """
        vecs = embed([d["text"] for d in docs])
        for d, v in zip(docs, vecs):
            d["embedding"] = v.tobytes()  # RedisVL will cast for hash
        await self.index.load(docs)

    async def search(self, r: redis.Redis, patient_id: str, query: str, k: int = 6):
        qvec = embed([query])[0].tolist()
        tag_filter = Tag("patient_id") == patient_id
        q = VectorQuery(
            vector=qvec,
            vector_field_name=VECTOR_FIELD,
            return_fields=RETURN_FIELDS,
            filter_expression=tag_filter,
            num_results=k,
            dtype="float32",
        )
        results = await self.index.query(q)
        return results or []