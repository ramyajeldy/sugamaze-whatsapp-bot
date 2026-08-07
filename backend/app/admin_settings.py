"""
JSON-backed store for admin-editable content: canned WhatsApp messages and
knowledge-base files, scoped per tenant. Lives next to the vector store on
the persistent disk (same volume Render mounts for CHROMA_DIR) so edits made
through the admin panel survive redeploys — unlike files shipped in the git
repo, which get reset every time Render redeploys from a new commit.
"""
import json
import pathlib

from .config import get_settings
from . import tenants

_settings = get_settings()

ADMIN_DATA_ROOT = pathlib.Path(_settings.chroma_dir).parent / "admin_data"


def _tenant_dir(tenant_id: str) -> pathlib.Path:
    return ADMIN_DATA_ROOT / tenant_id


def _messages_file(tenant_id: str) -> pathlib.Path:
    return _tenant_dir(tenant_id) / "messages.json"


def _knowledge_dir(tenant_id: str) -> pathlib.Path:
    return _tenant_dir(tenant_id) / "knowledge"


def _default_messages(tenant_id: str) -> dict:
    return dict(tenants.get_tenant(tenant_id).default_messages)


def _ensure_dirs(tenant_id: str):
    _tenant_dir(tenant_id).mkdir(parents=True, exist_ok=True)
    _knowledge_dir(tenant_id).mkdir(parents=True, exist_ok=True)


def migrate_legacy_admin_data(legacy_tenant_id: str = "sugamaze"):
    """One-time move of the pre-multi-tenant layout (admin_data/messages.json,
    admin_data/knowledge/*.md) into admin_data/<legacy_tenant_id>/. Safe to
    call on every startup — no-ops once the legacy files are gone. Protects
    Sugamaze's real persisted content on the production disk during the
    multi-tenant cutover."""
    legacy_messages = ADMIN_DATA_ROOT / "messages.json"
    legacy_knowledge = ADMIN_DATA_ROOT / "knowledge"
    new_messages = _messages_file(legacy_tenant_id)
    new_knowledge = _knowledge_dir(legacy_tenant_id)

    if legacy_messages.exists() and not new_messages.exists():
        _ensure_dirs(legacy_tenant_id)
        new_messages.write_bytes(legacy_messages.read_bytes())
        legacy_messages.unlink()

    if legacy_knowledge.exists() and legacy_knowledge.is_dir():
        _ensure_dirs(legacy_tenant_id)
        for md_file in legacy_knowledge.glob("*.md"):
            dest = new_knowledge / md_file.name
            if not dest.exists():
                dest.write_bytes(md_file.read_bytes())
            md_file.unlink()
        try:
            legacy_knowledge.rmdir()
        except OSError:
            pass  # not empty (unexpected extra files) — leave it, harmless


def get_messages(tenant_id: str) -> dict:
    _ensure_dirs(tenant_id)
    defaults = _default_messages(tenant_id)
    messages_file = _messages_file(tenant_id)
    if messages_file.exists():
        try:
            saved = json.loads(messages_file.read_text(encoding="utf-8"))
            return {**defaults, **saved}
        except Exception:
            pass
    return defaults


def get_message(tenant_id: str, key: str) -> str:
    return get_messages(tenant_id).get(key, _default_messages(tenant_id).get(key, ""))


def save_messages(tenant_id: str, updates: dict):
    """Merge `updates` into the persisted settings for this tenant. Any key
    is accepted — canned-message keys are tenant-defined (a bakery has
    order_text/allergy_text, an enrichment center has pricing_text/
    enrollment_text), not a fixed schema."""
    current = get_messages(tenant_id)
    current.update(updates)
    _ensure_dirs(tenant_id)
    _messages_file(tenant_id).write_text(
        json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def seed_knowledge_from_repo(tenant_id: str, repo_knowledge_dir: pathlib.Path):
    """One-time bootstrap: copy a tenant's shipped knowledge/*.md into the
    persistent admin dir if a file with that name doesn't already live
    there. After this, the admin dir — not the repo — is the source of
    truth."""
    if not repo_knowledge_dir.exists():
        return
    _ensure_dirs(tenant_id)
    dest_dir = _knowledge_dir(tenant_id)
    for md_file in repo_knowledge_dir.glob("*.md"):
        dest = dest_dir / md_file.name
        if not dest.exists():
            dest.write_text(md_file.read_text(encoding="utf-8"), encoding="utf-8")


def list_knowledge_files(tenant_id: str) -> list[str]:
    _ensure_dirs(tenant_id)
    return sorted(p.name for p in _knowledge_dir(tenant_id).glob("*.md"))


def _safe_path(tenant_id: str, filename: str) -> pathlib.Path:
    """Reject anything that isn't a bare '<name>.md' — no path separators,
    no traversal, no hidden files."""
    name = pathlib.PurePosixPath(filename).name
    if name != filename or not name.endswith(".md") or name in {".md", ""}:
        raise ValueError(f"invalid knowledge filename: {filename!r}")
    return _knowledge_dir(tenant_id) / name


def get_knowledge_text(tenant_id: str, filename: str) -> str:
    _ensure_dirs(tenant_id)
    path = _safe_path(tenant_id, filename)
    if not path.exists():
        raise FileNotFoundError(filename)
    return path.read_text(encoding="utf-8")


def save_knowledge_text(tenant_id: str, filename: str, text: str):
    _ensure_dirs(tenant_id)
    path = _safe_path(tenant_id, filename)
    path.write_text(text, encoding="utf-8")
