"""
Admin panel: lets the shop owner update store details, canned messages, and
knowledge-base content without touching code or waiting for a deploy.

Auth is a single static username/password (HTTP Basic) — good enough for a
one-owner shop, not meant to scale to multiple admin accounts.
"""
import secrets

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel

from . import admin_settings, ingest, store
from .config import get_settings

router = APIRouter()
_settings = get_settings()
_security = HTTPBasic()


def require_admin(credentials: HTTPBasicCredentials = Depends(_security)):
    valid_user = secrets.compare_digest(credentials.username, _settings.admin_username)
    valid_pass = secrets.compare_digest(credentials.password, _settings.admin_password)
    if not (valid_user and valid_pass):
        raise HTTPException(
            status_code=401,
            detail="Invalid admin credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


class MessagesUpdate(BaseModel):
    hours_text: str | None = None
    location_text: str | None = None
    order_text: str | None = None
    allergy_text: str | None = None
    closing_line: str | None = None
    team_escalation_line: str | None = None
    menu_text: str | None = None
    flavours_text: str | None = None


class KnowledgeUpdate(BaseModel):
    text: str


@router.get("/admin", response_class=HTMLResponse)
def admin_page(_: str = Depends(require_admin)):
    from pathlib import Path
    html_path = Path(__file__).parent.parent / "static" / "admin.html"
    return FileResponse(html_path)


@router.get("/admin/api/messages")
def get_messages(_: str = Depends(require_admin)):
    return admin_settings.get_messages()


@router.put("/admin/api/messages")
def update_messages(body: MessagesUpdate, _: str = Depends(require_admin)):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    admin_settings.save_messages(updates)
    return admin_settings.get_messages()


@router.get("/admin/api/knowledge")
def list_knowledge(_: str = Depends(require_admin)):
    return {"files": admin_settings.list_knowledge_files()}


@router.get("/admin/api/knowledge/{filename}")
def get_knowledge(filename: str, _: str = Depends(require_admin)):
    try:
        return {"filename": filename, "text": admin_settings.get_knowledge_text(filename)}
    except FileNotFoundError:
        raise HTTPException(404, "Knowledge file not found")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/admin/api/knowledge/{filename}")
def update_knowledge(filename: str, body: KnowledgeUpdate, _: str = Depends(require_admin)):
    """Save the edited file, then re-ingest it into the live vector store —
    old chunks from the previous version are removed first so nothing stale
    lingers alongside the update."""
    try:
        admin_settings.save_knowledge_text(filename, body.text)
    except ValueError as e:
        raise HTTPException(400, str(e))

    tenant_id = _settings.default_tenant_id
    store.delete_by_source(tenant_id, filename)
    try:
        if filename == "faq.md":
            n = ingest.ingest_faq_md(tenant_id, filename, body.text)
        else:
            n = ingest.ingest_text(tenant_id, filename, body.text)
    except Exception as e:
        raise HTTPException(500, f"Saved, but re-ingest failed: {e}")

    return {"filename": filename, "ingested_chunks": n}
