"""
Self-healing knowledge base: every startup wipes and rebuilds each tenant's
vector store from that tenant's canonical sources. This runs unconditionally
(not just when empty) because a *partial* dataset — e.g. from a disk that
didn't fully persist, or stale chunks from an old chunk-size/embedding
config — is just as dangerous as an empty one and otherwise never gets
fixed. Runs in the background so /health responds immediately.

Per-tenant seed knowledge ships in backend/tenants/<tenant_id>/knowledge/
and bootstraps admin_data/<tenant_id>/knowledge/ on first run; after that,
admin-panel edits are the source of truth.
"""
import asyncio
import logging
import pathlib

from . import ingest, store, admin_settings, tenants

logger = logging.getLogger("autoseed")

TENANTS_DIR = pathlib.Path(__file__).parent.parent / "tenants"

# Voyage AI free tier without a payment method on file allows 3 requests/min.
SECONDS_BETWEEN_REQUESTS = 22


def _repo_knowledge_dir(tenant_id: str) -> pathlib.Path:
    return TENANTS_DIR / tenant_id / "knowledge"


async def reseed_tenant(tenant):
    tenant_id = tenant.tenant_id
    logger.info(f"[autoseed] rebuilding tenant '{tenant_id}' from scratch in background")
    store.reset_collection(tenant_id)

    # Bootstrap the persistent admin knowledge dir from the repo's shipped
    # files on first run only — after that, admin-panel edits are the source
    # of truth and survive redeploys (unlike the repo copy, which resets on
    # every deploy).
    admin_settings.seed_knowledge_from_repo(tenant_id, _repo_knowledge_dir(tenant_id))

    for filename in admin_settings.list_knowledge_files(tenant_id):
        try:
            text = admin_settings.get_knowledge_text(tenant_id, filename)
            if filename == "faq.md":
                # FAQ file uses Q&A pairs — one chunk per pair so retrieval
                # always surfaces the exact reviewed answer, not a mixed blob.
                n = ingest.ingest_faq_md(tenant_id, filename, text)
            else:
                n = ingest.ingest_text(tenant_id, filename, text)
            logger.info(f"[autoseed][{tenant_id}] ingested {filename}: {n} chunks")
        except Exception as e:
            logger.error(f"[autoseed][{tenant_id}] failed on {filename}: {e}")
        await asyncio.sleep(SECONDS_BETWEEN_REQUESTS)

    for url in tenant.seed_urls:
        try:
            n = ingest.ingest_url(tenant_id, url)
            logger.info(f"[autoseed][{tenant_id}] ingested {url}: {n} chunks")
        except Exception as e:
            logger.error(f"[autoseed][{tenant_id}] failed on {url}: {e}")
        await asyncio.sleep(SECONDS_BETWEEN_REQUESTS)

    logger.info(f"[autoseed] done — tenant '{tenant_id}' now has "
                f"{store.stats(tenant_id)['chunks']} chunks")


async def reseed_all():
    """Rebuild every configured tenant's knowledge base, one after another."""
    admin_settings.migrate_legacy_admin_data()
    for tenant in tenants.all_tenants():
        try:
            await reseed_tenant(tenant)
        except Exception as e:
            logger.error(f"[autoseed] tenant '{tenant.tenant_id}' failed entirely: {e}")
