import os
from functools import lru_cache

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

class Settings:
    # Anthropic
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
    claude_model: str = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

    # Embeddings (Voyage AI — no local model, low memory footprint)
    voyage_api_key: str = os.environ.get("VOYAGE_API_KEY", "")
    voyage_model: str = os.environ.get("VOYAGE_MODEL", "voyage-3.5-lite")

    # Vector store
    chroma_dir: str = os.environ.get("CHROMA_DIR", "./chroma_data")

    # Retrieval / grounding
    top_k: int = int(os.environ.get("TOP_K", "5"))
    # Cosine distance: 0 = identical, 2 = opposite. Above this, we treat a chunk
    # as "not relevant" and refuse rather than risk a hallucination.
    max_distance: float = float(os.environ.get("MAX_DISTANCE", "0.75"))

    # Chunking
    chunk_size: int = int(os.environ.get("CHUNK_SIZE", "800"))
    chunk_overlap: int = int(os.environ.get("CHUNK_OVERLAP", "120"))

    # WhatsApp (Meta Cloud API). One Meta App and one webhook serve every
    # tenant, so the verify token is process-wide; per-tenant phone number IDs
    # live in backend/tenants/*.yaml and per-tenant access tokens come from
    # WHATSAPP_TOKEN__<TENANT_ID_UPPER> env vars (see app/tenants.py).
    whatsapp_verify_token: str = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")

    # Idle check-in: nudge a customer who's gone quiet mid-conversation.
    idle_checkin_seconds: float = float(os.environ.get("IDLE_CHECKIN_SECONDS", "60"))

    # Rebuild every tenant's vector store on startup. On by default (the
    # self-healing behavior production relies on); set false locally to reuse
    # existing chroma_data instead of waiting out the reseed rate limits.
    autoseed_on_startup: bool = os.environ.get("AUTOSEED_ON_STARTUP", "true").lower() != "false"

    # Email (SMTP) — shared sender; each tenant's recipient address is in its
    # own YAML config.
    smtp_host: str = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port: int = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user: str = os.environ.get("SMTP_USER", "")
    smtp_password: str = os.environ.get("SMTP_PASSWORD", "")

    # Admin panel (static login — set these in Render env vars, not the repo)
    admin_username: str = os.environ.get("ADMIN_USERNAME", "admin")
    admin_password: str = os.environ.get("ADMIN_PASSWORD", "changeme")


@lru_cache
def get_settings() -> "Settings":
    return Settings()
