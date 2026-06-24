"""
Self-healing knowledge base: every startup wipes and rebuilds the tenant's
vector store from the canonical Sugamaze sources. This runs unconditionally
(not just when empty) because a *partial* dataset — e.g. from a disk that
didn't fully persist, or stale chunks from an old chunk-size/embedding
config — is just as dangerous as an empty one and otherwise never gets
fixed. Runs in the background so /health responds immediately.
"""
import asyncio
import logging
import pathlib

from . import ingest, store

logger = logging.getLogger("autoseed")

KNOWLEDGE_DIR = pathlib.Path(__file__).parent.parent / "knowledge"

WEBSITE_URLS = [
    "https://sugamaze.ca/about-us/",
    "https://sugamaze.ca/contact-us/",
    "https://sugamaze.ca/privacy-policy/",
    "https://sugamaze.ca/refund_returns/",
    "https://sugamaze.ca/custom-cake-builder/",
    "https://sugamaze.ca/dessert-cups/",
    "https://sugamaze.ca/cup-cakes/",
    "https://sugamaze.ca/patties-puffs/",
    "https://sugamaze.ca/cake-pops/",
    "https://sugamaze.ca/wedding-cakes/",
    "https://sugamaze.ca/birthday-cakes/",
    "https://sugamaze.ca/photo-cakes/",
    "https://sugamaze.ca/theme-based-cakes/",
    "https://sugamaze.ca/sweet-16-cakes/",
    "https://sugamaze.ca/gender-reveal/",
    "https://sugamaze.ca/all-cakes/",
    "https://sugamaze.ca/anniversary-cakes/",
    "https://sugamaze.ca/valentine-cakes/",
    "https://sugamaze.ca/ready-to-eat-cakes/",
    "https://sugamaze.ca/graduation-cakes/",
]

# Voyage AI free tier without a payment method on file allows 3 requests/min.
SECONDS_BETWEEN_REQUESTS = 22


async def reseed_if_empty(tenant_id: str):
    logger.info(f"[autoseed] rebuilding tenant '{tenant_id}' from scratch in background")
    store.reset_collection(tenant_id)

    for md_file in sorted(KNOWLEDGE_DIR.glob("*.md")):
        try:
            text = md_file.read_text(encoding="utf-8")
            n = ingest.ingest_text(tenant_id, md_file.name, text)
            logger.info(f"[autoseed] ingested {md_file.name}: {n} chunks")
        except Exception as e:
            logger.error(f"[autoseed] failed on {md_file.name}: {e}")
        await asyncio.sleep(SECONDS_BETWEEN_REQUESTS)

    for url in WEBSITE_URLS:
        try:
            n = ingest.ingest_url(tenant_id, url)
            logger.info(f"[autoseed] ingested {url}: {n} chunks")
        except Exception as e:
            logger.error(f"[autoseed] failed on {url}: {e}")
        await asyncio.sleep(SECONDS_BETWEEN_REQUESTS)

    logger.info(f"[autoseed] done — tenant '{tenant_id}' now has "
                f"{store.stats(tenant_id)['chunks']} chunks")
