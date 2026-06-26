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

from . import autoseed, ingest, notify, rag, state, store, whatsapp
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


@app.on_event("startup")
async def startup_idle_checkin_loop():
    asyncio.create_task(_idle_checkin_loop())


WELCOME_MENU_ROWS = [
    ("opt_order", "Place a custom order"),
    ("opt_menu", "View our menu"),
    ("opt_hours", "Store hours"),
    ("opt_address", "Store address"),
    ("opt_team", "Talk to our team"),
    ("opt_other", "Others"),
]


def _send_welcome_menu(to: str):
    whatsapp.send_list(
        to,
        header_text="Thank you for contacting Sugamaze! 🙂",
        body_text="Tell me what I can help you with today",
        button_text="Choose an option",
        rows=WELCOME_MENU_ROWS,
    )


async def _idle_checkin_loop():
    while True:
        await asyncio.sleep(5)
        for phone in state.idle_customers(_settings.idle_checkin_seconds):
            try:
                whatsapp.send_buttons(
                    phone,
                    "Hello, there? Would you like to continue chatting?",
                    [("idle_yes", "Yes"), ("idle_no", "No")],
                )
            except Exception as e:
                print(f"[idle-checkin] failed to message {phone}: {e}")
            finally:
                state.mark_followup_sent(phone)


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
    return {
        "escalation_whatsapp_to": _settings.escalation_whatsapp_to,
        "escalation_email": _settings.escalation_email,
        "whatsapp_phone_number_id_set": bool(_settings.whatsapp_phone_number_id),
        "whatsapp_token_set": bool(_settings.whatsapp_token),
        "smtp_user_set": bool(_settings.smtp_user),
        "last_escalation_attempt": notify.last_attempt,
        "last_escalation_result": notify.last_error,
        "recent_whatsapp_status_callbacks": whatsapp.recent_statuses,
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
    whatsapp.extract_status(payload)

    button = whatsapp.extract_button_reply(payload)
    if button is not None:
        from_number, button_id = button
        if button_id == "idle_yes":
            state.touch(from_number)
            whatsapp.send_message(from_number, "How may I help you further?")
        elif button_id == "idle_no":
            state.end_conversation(from_number)
            whatsapp.send_message(from_number, rag.CLOSING_LINE)
        return {"ok": True}

    list_reply = whatsapp.extract_list_reply(payload)
    if list_reply is not None:
        from_number, row_id = list_reply
        state.touch(from_number)
        if row_id == "opt_order":
            notify.notify_escalation(from_number, "Customer wants to place a custom order.")
            whatsapp.send_message(from_number, rag.ORDER_TEXT)
        elif row_id == "opt_menu":
            whatsapp.send_message(from_number, rag.MENU_TEXT)
        elif row_id == "opt_hours":
            whatsapp.send_message(from_number, rag.HOURS_TEXT)
        elif row_id == "opt_address":
            whatsapp.send_message(from_number, rag.LOCATION_TEXT)
        elif row_id == "opt_team":
            notify.notify_escalation(from_number, "Customer asked to talk to the team directly.")
            whatsapp.send_message(from_number, rag.TEAM_ESCALATION_LINE)
        elif row_id == "opt_other":
            whatsapp.send_message(from_number, "Sure! Go ahead and ask your question 😊")
        return {"ok": True}

    media = whatsapp.extract_media(payload)
    if media is not None:
        from_number, media_type, media_id, caption = media
        state.touch(from_number)
        notify.notify_order_media(from_number, media_type, media_id, caption)
        whatsapp.send_message(from_number, "Got it! Your design has been shared with our team 💕")
        return {"ok": True}

    parsed = whatsapp.extract_message(payload)
    if parsed is None:
        # Status callbacks (delivered/read) and non-text messages land here.
        return {"ok": True}

    # Greetings get the interactive welcome menu instead of plain text.
    greet_number, greet_text = parsed
    if rag.is_greeting(greet_text):
        state.touch(greet_number)
        _send_welcome_menu(greet_number)
        return {"ok": True}

    from_number, text = parsed
    state.touch(from_number)
    result = rag.answer(_settings.default_tenant_id, text, customer_phone=from_number)
    whatsapp.send_message(from_number, result["answer"])
    return {"ok": True}
