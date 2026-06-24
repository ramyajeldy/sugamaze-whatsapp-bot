"""
GroundedBot API — Phase 1: a tenant-aware, grounded Q&A chatbot for local
businesses. Answers strictly from ingested websites, PDFs, and text.

Run:
    uvicorn app.main:app --reload --port 8000

Phase 2 (scheduling, feedback, order capture + summaries) plugs in as new
routes + tool-use on top of this same core. Not built yet — kept out on purpose
so Phase 1 stays demoable.
"""
import asyncio

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from . import autoseed, ingest, rag, store, whatsapp
from .config import get_settings
from .schemas import ChatRequest, IngestUrlRequest, IngestTextRequest

app = FastAPI(title="GroundedBot", version="0.1.0")
_settings = get_settings()

# Open CORS for local testing. TIGHTEN to the client's domain before production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_autoseed():
    # Runs in the background so the server starts answering /health immediately
    # even while re-seeding (which can take several minutes under rate limits).
    asyncio.create_task(autoseed.reseed_if_empty(_settings.default_tenant_id))


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/ingest/url")
def ingest_url(req: IngestUrlRequest):
    try:
        n = ingest.ingest_url(req.tenant_id, req.url)
    except Exception as e:
        raise HTTPException(400, str(e))
    return {"ingested_chunks": n, **store.stats(req.tenant_id)}


@app.post("/ingest/text")
def ingest_text(req: IngestTextRequest):
    try:
        n = ingest.ingest_text(req.tenant_id, req.source, req.text)
    except Exception as e:
        raise HTTPException(400, str(e))
    return {"ingested_chunks": n, **store.stats(req.tenant_id)}


@app.post("/ingest/pdf")
async def ingest_pdf(tenant_id: str = Form(...), file: UploadFile = File(...)):
    data = await file.read()
    try:
        n = ingest.ingest_pdf_bytes(tenant_id, file.filename, data)
    except Exception as e:
        raise HTTPException(400, str(e))
    return {"ingested_chunks": n, **store.stats(tenant_id)}


@app.post("/chat")
def chat(req: ChatRequest):
    if not req.question.strip():
        raise HTTPException(400, "Empty question")
    return rag.answer(req.tenant_id, req.question)


@app.get("/stats/{tenant_id}")
def get_stats(tenant_id: str):
    return store.stats(tenant_id)


@app.get("/debug/config")
def debug_config():
    # Temporary diagnostic endpoint — no secrets exposed, just presence/value
    # of non-sensitive settings used by the escalation notification path.
    from . import notify
    return {
        "escalation_whatsapp_to": _settings.escalation_whatsapp_to,
        "escalation_email": _settings.escalation_email,
        "whatsapp_phone_number_id_set": bool(_settings.whatsapp_phone_number_id),
        "whatsapp_token_set": bool(_settings.whatsapp_token),
        "smtp_user_set": bool(_settings.smtp_user),
        "last_escalation_attempt": notify.last_attempt,
        "last_escalation_result": notify.last_error,
    }


@app.get("/webhook/whatsapp")
def whatsapp_verify(request: Request):
    params = request.query_params
    challenge = whatsapp.verify(
        params.get("hub.mode", ""),
        params.get("hub.verify_token", ""),
        params.get("hub.challenge", ""),
    )
    if challenge is None:
        raise HTTPException(403, "Verification failed")
    return PlainTextResponse(challenge)


@app.post("/webhook/whatsapp")
async def whatsapp_incoming(request: Request):
    payload = await request.json()
    parsed = whatsapp.extract_message(payload)
    if parsed is None:
        # Status callbacks (delivered/read) and non-text messages land here.
        return {"ok": True}

    from_number, text = parsed
    result = rag.answer(_settings.default_tenant_id, text, customer_phone=from_number)
    whatsapp.send_message(from_number, result["answer"])
    return {"ok": True}
