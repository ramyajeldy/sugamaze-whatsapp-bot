"""
GroundedBot API — a multi-tenant, grounded Q&A chatbot for local businesses.
Answers strictly from ingested websites, PDFs, and text.

One deployment serves many tenants: each has a YAML behavior config in
backend/tenants/, its own Chroma collection, its own admin-editable content
under admin_data/<tenant_id>/, and its own WhatsApp number. Inbound webhooks
route to a tenant by the Meta phone_number_id they were sent to.

Run:
    uvicorn app.main:app --reload --port 8000
"""
import asyncio

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from . import admin, admin_settings, autoseed, ingest, notify, rag, state, store, tenants, whatsapp
from .config import get_settings
from .schemas import ChatRequest, IngestUrlRequest, IngestTextRequest

app = FastAPI(title="GroundedBot", version="0.2.0")
_settings = get_settings()
app.include_router(admin.router)

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
    if _settings.autoseed_on_startup:
        asyncio.create_task(autoseed.reseed_all())
    else:
        admin_settings.migrate_legacy_admin_data()
        print("[autoseed] skipped (AUTOSEED_ON_STARTUP=false)")


@app.on_event("startup")
async def startup_idle_checkin_loop():
    asyncio.create_task(_idle_checkin_loop())


def _send_welcome_menu(tenant, to: str):
    menu = tenant.welcome_menu
    whatsapp.send_list(
        whatsapp.creds_for(tenant),
        to,
        header_text=menu["header_text"],
        body_text=menu["body_text"],
        button_text=menu["button_text"],
        rows=[(row["id"], row["title"]) for row in menu["rows"]],
    )


def _handle_menu_selection(tenant, from_number: str, row_id: str) -> bool:
    """Run the tenant-defined action for a welcome-menu row. Returns False if
    the row id isn't in this tenant's menu."""
    row = next((r for r in tenant.welcome_menu.get("rows", []) if r["id"] == row_id), None)
    if row is None:
        return False

    creds = whatsapp.creds_for(tenant)
    action = row["action"]
    kind = action["type"]

    if kind == "canned":
        whatsapp.send_message(creds, from_number, admin_settings.get_message(tenant.tenant_id, action["key"]))
    elif kind == "notify_and_canned":
        if action.get("notify") == "priority_lead":
            notify.notify_priority_lead(tenant, from_number, action.get("notify_label", row["title"]))
        elif action.get("notify") == "escalation":
            notify.notify_escalation(tenant, from_number, action.get("reason", row["title"]))
        whatsapp.send_message(creds, from_number, admin_settings.get_message(tenant.tenant_id, action["key"]))
    elif kind == "rag_query":
        result = rag.answer(tenant.tenant_id, action["query"], customer_phone=from_number)
        whatsapp.send_message(creds, from_number, result["answer"])
    elif kind == "freeform_prompt":
        whatsapp.send_message(creds, from_number, action["text"])
    return True


async def _idle_checkin_loop():
    while True:
        await asyncio.sleep(5)
        for tenant_id, phone in state.idle_customers(_settings.idle_checkin_seconds):
            try:
                tenant = tenants.get_tenant(tenant_id)
                whatsapp.send_buttons(
                    whatsapp.creds_for(tenant),
                    phone,
                    "Hello, there? Would you like to continue chatting?",
                    [("idle_yes", "Yes"), ("idle_no", "No")],
                )
            except Exception as e:
                print(f"[idle-checkin] failed to message {phone} for {tenant_id}: {e}")
            finally:
                state.mark_followup_sent(tenant_id, phone)


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/tenants")
def list_tenants():
    return {
        "tenants": [
            {"tenant_id": t.tenant_id, "business_name": t.business_name, "vertical": t.vertical}
            for t in tenants.all_tenants()
        ]
    }


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
    try:
        return rag.answer(req.tenant_id, req.question)
    except KeyError as e:
        raise HTTPException(404, str(e))


@app.get("/stats/{tenant_id}")
def get_stats(tenant_id: str):
    return store.stats(tenant_id)


@app.get("/debug/config")
def debug_config():
    # Temporary diagnostic endpoint — no secrets exposed, just presence/value
    # of non-sensitive settings used by the escalation notification path.
    return {
        "tenants": [
            {
                "tenant_id": t.tenant_id,
                "escalation_whatsapp_to": t.escalation_whatsapp_to,
                "escalation_email": t.escalation_email,
                "whatsapp_phone_number_id": t.whatsapp_phone_number_id,
                "whatsapp_token_set": bool(_token_present(t)),
            }
            for t in tenants.all_tenants()
        ],
        "smtp_user_set": bool(_settings.smtp_user),
        "last_escalation_attempt": notify.last_attempt,
        "last_escalation_result": notify.last_error,
        "recent_whatsapp_status_callbacks": whatsapp.recent_statuses,
    }


def _token_present(tenant) -> bool:
    try:
        return bool(tenant.whatsapp_token)
    except RuntimeError:
        return False


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

    phone_number_id = whatsapp.extract_phone_number_id(payload)
    tenant = tenants.resolve_tenant_by_phone_number_id(phone_number_id) if phone_number_id else None
    if tenant is None:
        # Not a number we serve (or a status-only callback with no metadata).
        # Ack so Meta doesn't retry; nothing to answer.
        print(f"[webhook] no tenant for phone_number_id={phone_number_id!r}")
        return {"ok": True}

    tenant_id = tenant.tenant_id
    try:
        creds = whatsapp.creds_for(tenant)
    except RuntimeError as e:
        # Misconfigured tenant (missing WHATSAPP_TOKEN__<ID> env var) — ack
        # so Meta doesn't retry, but don't crash the whole webhook over it.
        print(f"[webhook] {e}")
        return {"ok": True}

    button = whatsapp.extract_button_reply(payload)
    if button is not None:
        from_number, button_id = button
        if button_id == "idle_yes":
            state.touch(tenant_id, from_number)
            whatsapp.send_message(creds, from_number, "How may I help you further?")
        elif button_id == "idle_no":
            state.end_conversation(tenant_id, from_number)
            whatsapp.send_message(creds, from_number, rag.CLOSING_LINE(tenant_id))
        return {"ok": True}

    list_reply = whatsapp.extract_list_reply(payload)
    if list_reply is not None:
        from_number, row_id = list_reply
        state.touch(tenant_id, from_number)
        _handle_menu_selection(tenant, from_number, row_id)
        return {"ok": True}

    media = whatsapp.extract_media(payload)
    if media is not None:
        from_number, media_type, media_id, caption = media
        state.touch(tenant_id, from_number)
        notify.notify_media(tenant, from_number, media_type, media_id, caption)
        whatsapp.send_message(creds, from_number, tenant.media_received_text)
        return {"ok": True}

    parsed = whatsapp.extract_message(payload)
    if parsed is None:
        # Status callbacks (delivered/read) and non-text messages land here.
        return {"ok": True}

    # Greetings get the interactive welcome menu instead of plain text, and
    # start a fresh conversation — old history shouldn't bleed into a new chat.
    from_number, text = parsed
    if rag.is_greeting(tenant_id, text):
        state.touch(tenant_id, from_number)
        state.clear_history(tenant_id, from_number)
        _send_welcome_menu(tenant, from_number)
        return {"ok": True}

    state.touch(tenant_id, from_number)
    history = state.get_history(tenant_id, from_number)
    result = rag.answer(tenant_id, text, customer_phone=from_number, history=history)
    whatsapp.send_message(creds, from_number, result["answer"])
    state.append_turn(tenant_id, from_number, "user", text)
    state.append_turn(tenant_id, from_number, "assistant", result["answer"])
    return {"ok": True}
