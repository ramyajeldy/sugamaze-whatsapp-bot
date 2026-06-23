"""
Vector store wrapper. Tenant-aware from day one: every business gets its own
Chroma collection, so one customer's documents can never leak into another's
answers. This is the cheap multi-tenancy that saves you a rewrite at customer #2.

Embeddings come from Voyage AI's API (Anthropic's recommended embedding
partner) — no local model, so no PyTorch and a much smaller memory footprint
than the SentenceTransformer alternative.
"""
import chromadb
from chromadb.utils import embedding_functions

from .config import get_settings

_settings = get_settings()
_client = chromadb.PersistentClient(path=_settings.chroma_dir)

_embed_fn = embedding_functions.VoyageAIEmbeddingFunction(
    api_key=_settings.voyage_api_key,
    model_name=_settings.voyage_model,
)


def _collection(tenant_id: str):
    # cosine space so distances are comparable across collections
    return _client.get_or_create_collection(
        name=f"tenant_{tenant_id}",
        embedding_function=_embed_fn,
        metadata={"hnsw:space": "cosine"},
    )


def add_chunks(tenant_id, ids, documents, metadatas):
    col = _collection(tenant_id)
    # upsert so re-ingesting the same source updates instead of duplicating
    col.upsert(ids=ids, documents=documents, metadatas=metadatas)


def query(tenant_id, text, top_k):
    col = _collection(tenant_id)
    res = col.query(
        query_texts=[text],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )
    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]
    return [
        {"text": d, "metadata": m, "distance": dist}
        for d, m, dist in zip(docs, metas, dists)
    ]


def stats(tenant_id):
    col = _collection(tenant_id)
    return {"tenant_id": tenant_id, "chunks": col.count()}
