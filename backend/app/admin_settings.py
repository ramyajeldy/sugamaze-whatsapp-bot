"""
JSON-backed store for admin-editable content: canned WhatsApp messages and
knowledge-base files. Lives next to the vector store on the persistent disk
(same volume Render mounts for CHROMA_DIR) so edits made through the admin
panel survive redeploys — unlike files shipped in the git repo, which get
reset every time Render redeploys from a new commit.
"""
import json
import pathlib

from .config import get_settings

_settings = get_settings()

ADMIN_DATA_DIR = pathlib.Path(_settings.chroma_dir).parent / "admin_data"
MESSAGES_FILE = ADMIN_DATA_DIR / "messages.json"
KNOWLEDGE_DIR = ADMIN_DATA_DIR / "knowledge"

# Shipped defaults — used the first time the admin panel runs, and as a
# fallback for any key that's never been edited.
DEFAULT_MESSAGES = {
    "hours_text": (
        "🕐 *Monday:* 11:00 am – 8:00 pm\n"
        "❌ *Tuesday:* Closed\n"
        "🕐 *Wednesday – Friday:* 11:00 am – 8:00 pm\n"
        "🕐 *Saturday & Sunday:* 10:00 am – 9:00 pm"
    ),
    "location_text": "We're located at *30 St Thomas St, Whitby, ON L1M 1H1* (Durham Region, Ontario). 📍",
    "order_text": (
        "Please leave your name, order details, date required, and upload any "
        "design ideas, and my team will get back to you with pricing and order "
        "confirmation during our business hours 😊\n\n"
        "You can also reach us directly at:\n"
        "📞 *+1 (905) 655-7878*\n"
        "✉️ *info@sugamaze.ca*\n\n"
        "Thank you for choosing Sugamaze 💕"
    ),
    "allergy_text": (
        "For allergy and dietary questions, please contact our team directly "
        "for a safe, accurate answer:\n\n"
        "📞 *+1 (905) 655-7878*\n"
        "✉️ *info@sugamaze.ca*\n\n"
        "Your safety is our priority — the team will be happy to help! 😊"
    ),
    "closing_line": "Thank you for contacting Sugamaze! Hope to see you around soon 🙂",
    "team_escalation_line": "A team member will reach out to you soon. Thank you for your patience.",
}


def _ensure_dirs():
    ADMIN_DATA_DIR.mkdir(parents=True, exist_ok=True)
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)


def get_messages() -> dict:
    _ensure_dirs()
    if MESSAGES_FILE.exists():
        try:
            saved = json.loads(MESSAGES_FILE.read_text(encoding="utf-8"))
            return {**DEFAULT_MESSAGES, **saved}
        except Exception:
            pass
    return dict(DEFAULT_MESSAGES)


def get_message(key: str) -> str:
    return get_messages().get(key, DEFAULT_MESSAGES.get(key, ""))


def save_messages(updates: dict):
    """Merge `updates` (only known keys) into the persisted settings."""
    current = get_messages()
    current.update({k: v for k, v in updates.items() if k in DEFAULT_MESSAGES})
    _ensure_dirs()
    MESSAGES_FILE.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")


def seed_knowledge_from_repo(repo_knowledge_dir: pathlib.Path):
    """One-time bootstrap: copy the repo's shipped knowledge/*.md into the
    persistent admin dir if a file with that name doesn't already live there.
    After this, the admin dir — not the repo — is the source of truth."""
    _ensure_dirs()
    for md_file in repo_knowledge_dir.glob("*.md"):
        dest = KNOWLEDGE_DIR / md_file.name
        if not dest.exists():
            dest.write_text(md_file.read_text(encoding="utf-8"), encoding="utf-8")


def list_knowledge_files() -> list[str]:
    _ensure_dirs()
    return sorted(p.name for p in KNOWLEDGE_DIR.glob("*.md"))


def _safe_path(filename: str) -> pathlib.Path:
    """Reject anything that isn't a bare '<name>.md' — no path separators,
    no traversal, no hidden files."""
    name = pathlib.PurePosixPath(filename).name
    if name != filename or not name.endswith(".md") or name in {".md", ""}:
        raise ValueError(f"invalid knowledge filename: {filename!r}")
    return KNOWLEDGE_DIR / name


def get_knowledge_text(filename: str) -> str:
    _ensure_dirs()
    path = _safe_path(filename)
    if not path.exists():
        raise FileNotFoundError(filename)
    return path.read_text(encoding="utf-8")


def save_knowledge_text(filename: str, text: str):
    _ensure_dirs()
    path = _safe_path(filename)
    path.write_text(text, encoding="utf-8")
