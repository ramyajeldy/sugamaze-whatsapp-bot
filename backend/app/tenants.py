"""
Tenant registry: loads backend/tenants/*.yaml at import time and exposes
lookup by tenant_id and by inbound WhatsApp phone_number_id.

Each YAML file is the tenant's *behavior config* — identity/tone for the
system prompt, deterministic shortcut categories, the welcome menu, default
canned messages, and seed sources. It's repo-committed and requires a
redeploy to change. Admin-editable *content* (live-edited canned message
text, knowledge base files) stays on the persistent disk under
admin_data/<tenant_id>/ — see admin_settings.py.

WhatsApp access tokens are secrets and never live in the YAML: each tenant's
token comes from an env var named WHATSAPP_TOKEN__<TENANT_ID_UPPER> (e.g.
WHATSAPP_TOKEN__SUGAMAZE).
"""
import os
import pathlib
from dataclasses import dataclass, field

import yaml

TENANTS_DIR = pathlib.Path(__file__).parent.parent / "tenants"


@dataclass
class TenantConfig:
    tenant_id: str
    business_name: str
    vertical: str
    whatsapp_phone_number_id: str
    escalation_email: str
    escalation_whatsapp_to: str

    identity_block: str
    topic_guardrail: str
    contact_phone: str
    contact_email: str
    escalation_text: str

    greetings: list[str]
    closing_phrases: list[str]
    shortcuts: list[dict] = field(default_factory=list)
    welcome_menu: dict = field(default_factory=dict)
    default_messages: dict = field(default_factory=dict)
    # Friendly labels for the admin panel's message editor, keyed by
    # default_messages key. Missing keys fall back to a humanized key name.
    message_labels: dict = field(default_factory=dict)
    seed_urls: list[str] = field(default_factory=list)
    media_received_text: str = "Got it! I've shared that with our team."

    @property
    def whatsapp_token(self) -> str:
        env_name = f"WHATSAPP_TOKEN__{self.tenant_id.upper()}"
        token = os.environ.get(env_name, "")
        if not token:
            raise RuntimeError(
                f"Missing WhatsApp token for tenant '{self.tenant_id}': "
                f"set env var {env_name}"
            )
        return token


REQUIRED_FIELDS = {
    "tenant_id", "business_name", "vertical", "whatsapp_phone_number_id",
    "escalation_email", "escalation_whatsapp_to", "identity_block",
    "topic_guardrail", "contact_phone", "contact_email", "escalation_text",
}


def _load_tenant(path: pathlib.Path) -> TenantConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    missing = REQUIRED_FIELDS - raw.keys()
    if missing:
        raise ValueError(f"{path}: missing required field(s) {sorted(missing)}")

    seed = raw.get("seed") or {}
    return TenantConfig(
        tenant_id=raw["tenant_id"],
        business_name=raw["business_name"],
        vertical=raw["vertical"],
        whatsapp_phone_number_id=str(raw["whatsapp_phone_number_id"]),
        escalation_email=raw["escalation_email"],
        escalation_whatsapp_to=str(raw["escalation_whatsapp_to"]),
        identity_block=raw["identity_block"].strip(),
        topic_guardrail=raw["topic_guardrail"].strip(),
        contact_phone=raw["contact_phone"],
        contact_email=raw["contact_email"],
        escalation_text=raw["escalation_text"].strip(),
        greetings=raw.get("greetings", ["hi", "hello", "hey"]),
        closing_phrases=raw.get("closing_phrases", ["thanks", "thank you", "bye"]),
        shortcuts=raw.get("shortcuts", []),
        welcome_menu=raw.get("welcome_menu", {}),
        default_messages=raw.get("default_messages", {}),
        message_labels=raw.get("message_labels", {}),
        seed_urls=seed.get("urls", []),
        media_received_text=raw.get(
            "media_received_text", "Got it! I've shared that with our team."
        ),
    )


def _load_all() -> dict[str, TenantConfig]:
    tenants = {}
    if not TENANTS_DIR.exists():
        return tenants
    for path in sorted(TENANTS_DIR.glob("*.yaml")):
        tenant = _load_tenant(path)
        if tenant.tenant_id in tenants:
            raise ValueError(f"Duplicate tenant_id '{tenant.tenant_id}' in {path}")
        tenants[tenant.tenant_id] = tenant
    return tenants


_TENANTS: dict[str, TenantConfig] = _load_all()
_BY_PHONE_NUMBER_ID: dict[str, str] = {
    t.whatsapp_phone_number_id: t.tenant_id for t in _TENANTS.values()
}


def reload():
    """Re-read all tenant YAML files. Useful for tests; not called at runtime
    otherwise since behavior config changes are expected to ship via deploy."""
    global _TENANTS, _BY_PHONE_NUMBER_ID
    _TENANTS = _load_all()
    _BY_PHONE_NUMBER_ID = {t.whatsapp_phone_number_id: t.tenant_id for t in _TENANTS.values()}


def get_tenant(tenant_id: str) -> TenantConfig:
    try:
        return _TENANTS[tenant_id]
    except KeyError:
        raise KeyError(f"Unknown tenant_id: {tenant_id!r}")


def all_tenants() -> list[TenantConfig]:
    return list(_TENANTS.values())


def resolve_tenant_by_phone_number_id(phone_number_id: str) -> "TenantConfig | None":
    tenant_id = _BY_PHONE_NUMBER_ID.get(phone_number_id)
    return _TENANTS.get(tenant_id) if tenant_id else None
