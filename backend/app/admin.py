"""
Admin panel: lets a business owner update canned messages and knowledge-base
content without touching code or waiting for a deploy.

Auth is a single static username/password (HTTP Basic) covering all tenants —
this is the operator's ("white-glove") console, not per-client logins. Add
per-tenant accounts before handing the URL directly to individual clients.
"""
import secrets

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel

from . import admin_settings, ingest, store, tenants, usage
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


def require_tenant(tenant_id: str):
    try:
        return tenants.get_tenant(tenant_id)
    except KeyError:
        raise HTTPException(404, f"Unknown tenant: {tenant_id}")


class MessagesUpdate(BaseModel):
    # Canned-message keys are tenant-defined (a bakery has order_text /
    # allergy_text; an enrichment center has pricing_text / enrollment_text),
    # so this is an open map rather than a fixed schema. Unknown keys are
    # rejected below against the tenant's own default_messages.
    messages: dict[str, str]


class KnowledgeUpdate(BaseModel):
    text: str


@router.get("/admin", response_class=HTMLResponse)
def admin_page(_: str = Depends(require_admin)):
    from pathlib import Path
    html_path = Path(__file__).parent.parent / "static" / "admin.html"
    return FileResponse(html_path)


@router.get("/admin/api/tenants")
def list_tenants(_: str = Depends(require_admin)):
    return {
        "tenants": [
            {"tenant_id": t.tenant_id, "business_name": t.business_name, "vertical": t.vertical}
            for t in tenants.all_tenants()
        ]
    }


@router.get("/admin/api/{tenant_id}/usage")
def get_usage(tenant_id: str, _: str = Depends(require_admin)):
    require_tenant(tenant_id)
    return usage.get_current_month_usage(tenant_id)


@router.get("/admin/api/{tenant_id}/messages")
def get_messages(tenant_id: str, _: str = Depends(require_admin)):
    tenant = require_tenant(tenant_id)
    return {
        "messages": admin_settings.get_messages(tenant_id),
        "labels": tenant.message_labels,
        "order": list(tenant.default_messages),
    }


@router.put("/admin/api/{tenant_id}/messages")
def update_messages(tenant_id: str, body: MessagesUpdate, _: str = Depends(require_admin)):
    tenant = require_tenant(tenant_id)
    known = set(tenant.default_messages)
    unknown = set(body.messages) - known
    if unknown:
        raise HTTPException(400, f"Unknown message key(s) for {tenant_id}: {sorted(unknown)}")
    admin_settings.save_messages(tenant_id, body.messages)
    return admin_settings.get_messages(tenant_id)


@router.get("/admin/api/{tenant_id}/knowledge")
def list_knowledge(tenant_id: str, _: str = Depends(require_admin)):
    require_tenant(tenant_id)
    return {"files": admin_settings.list_knowledge_files(tenant_id)}


@router.get("/admin/api/{tenant_id}/knowledge/{filename}")
def get_knowledge(tenant_id: str, filename: str, _: str = Depends(require_admin)):
    require_tenant(tenant_id)
    try:
        return {"filename": filename, "text": admin_settings.get_knowledge_text(tenant_id, filename)}
    except FileNotFoundError:
        raise HTTPException(404, "Knowledge file not found")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/admin/api/{tenant_id}/knowledge/{filename}")
def update_knowledge(tenant_id: str, filename: str, body: KnowledgeUpdate, _: str = Depends(require_admin)):
    """Save the edited file, then re-ingest it into the live vector store —
    old chunks from the previous version are removed first so nothing stale
    lingers alongside the update."""
    require_tenant(tenant_id)
    try:
        admin_settings.save_knowledge_text(tenant_id, filename, body.text)
    except ValueError as e:
        raise HTTPException(400, str(e))

    store.delete_by_source(tenant_id, filename)
    try:
        if filename == "faq.md":
            n = ingest.ingest_faq_md(tenant_id, filename, body.text)
        else:
            n = ingest.ingest_text(tenant_id, filename, body.text)
    except Exception as e:
        raise HTTPException(500, f"Saved, but re-ingest failed: {e}")

    return {"filename": filename, "ingested_chunks": n}
