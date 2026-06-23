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

    # Embeddings (local, free; swap to Voyage for production quality — see store.py)
    embed_model: str = os.environ.get("EMBED_MODEL", "all-MiniLM-L6-v2")

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

    # WhatsApp (Meta Cloud API)
    whatsapp_token: str = os.environ.get("WHATSAPP_TOKEN", "")
    whatsapp_phone_number_id: str = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
    whatsapp_verify_token: str = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")
    # Single-shop deployment: every WhatsApp message maps to this tenant.
    default_tenant_id: str = os.environ.get("DEFAULT_TENANT_ID", "sugamaze")

    # Escalation notifications (alert shop when bot can't answer)
    escalation_email: str = os.environ.get("ESCALATION_EMAIL", "info@sugamaze.ca")
    escalation_whatsapp_to: str = os.environ.get("ESCALATION_WHATSAPP_TO", "14056557878")

    # Email (SMTP)
    smtp_host: str = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port: int = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user: str = os.environ.get("SMTP_USER", "")
    smtp_password: str = os.environ.get("SMTP_PASSWORD", "")


@lru_cache
def get_settings() -> "Settings":
    return Settings()
