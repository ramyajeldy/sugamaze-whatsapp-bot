"""
Self-healing knowledge base: if the tenant's vector store is found empty on
startup (e.g. a hosting platform's disk didn't persist between deploys), this
re-ingests the canonical Sugamaze sources automatically in the background so
the bot recovers without manual intervention.
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
    if store.stats(tenant_id)["chunks"] > 0:
        logger.info(f"[autoseed] tenant '{tenant_id}' already has data, skipping")
        return

    logger.info(f"[autoseed] tenant '{tenant_id}' is empty — re-seeding in background")

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
