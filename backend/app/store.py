"""
Vector store wrapper. Tenant-aware from day one: every business gets its own
Chroma collection, so one customer's documents can never leak into another's
answers. This is the cheap multi-tenancy that saves you a rewrite at customer #2.

Default embeddings are a local SentenceTransformer model (free, no API key,
downloads once on first run). To upgrade to Voyage AI (Anthropic's recommended
embedding partner) for production-grade retrieval, replace _embed_fn with
Voyage's embedding function and set VOYAGE_API_KEY. The rest of the code is
unchanged.
"""
import chromadb
from chromadb.utils import embedding_functions

from .config import get_settings

_settings = get_settings()
_client = chromadb.PersistentClient(path=_settings.chroma_dir)

_embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name=_settings.embed_model
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
