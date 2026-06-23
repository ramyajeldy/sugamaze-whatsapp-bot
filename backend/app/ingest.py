"""
Ingestion pipeline: pull text from a URL, a PDF, or raw text, split into
overlapping chunks, and store them under a tenant. Each chunk keeps its source
so answers can be cited back to where they came from.
"""
import hashlib
import io

import trafilatura
from pypdf import PdfReader

from .config import get_settings
from . import store

_settings = get_settings()


def _chunk_text(text, size, overlap):
    text = " ".join(text.split())  # normalize whitespace
    chunks = []
    start, n = 0, len(text)
    while start < n:
        end = min(start + size, n)
        chunks.append(text[start:end])
        if end == n:
            break
        start = end - overlap
    return chunks


def _store_doc(tenant_id, source, title, text):
    chunks = _chunk_text(text, _settings.chunk_size, _settings.chunk_overlap)
    ids, docs, metas = [], [], []
    for i, ch in enumerate(chunks):
        uid = hashlib.sha1(f"{source}-{i}-{ch[:40]}".encode()).hexdigest()
        ids.append(uid)
        docs.append(ch)
        metas.append({"source": source, "title": title, "chunk": i})
    if ids:
        store.add_chunks(tenant_id, ids, docs, metas)
    return len(ids)


def ingest_url(tenant_id, url):
    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        raise ValueError(f"Could not fetch {url}")
    text = trafilatura.extract(downloaded, include_comments=False, include_tables=True)
    if not text:
        raise ValueError(f"No extractable text found at {url}")
    return _store_doc(tenant_id, source=url, title=url, text=text)


def ingest_pdf_bytes(tenant_id, filename, data):
    reader = PdfReader(io.BytesIO(data))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    if not text.strip():
        raise ValueError(
            "No extractable text in PDF (it may be a scanned image — OCR needed)."
        )
    return _store_doc(tenant_id, source=filename, title=filename, text=text)


def ingest_text(tenant_id, source, text):
    if not text.strip():
        raise ValueError("Empty text.")
    return _store_doc(tenant_id, source=source, title=source, text=text)
