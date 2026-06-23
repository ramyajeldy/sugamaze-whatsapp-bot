# GroundedBot

A tenant-aware, **grounded** Q&A chatbot for local businesses. It answers strictly
from sources you ingest (website pages, PDFs, raw text) and refuses — instead of
guessing — when the answer isn't in those sources. That refusal behavior is the
whole point: a bakery bot that invents an allergen is a liability, not a feature.

This is **Phase 1**. Phase 2 (scheduling, feedback, order capture + summaries)
builds on top of this same core.

---

## What's inside

```
groundedbot/
├── backend/
│   ├── app/
│   │   ├── main.py      # FastAPI routes: /ingest/url, /ingest/pdf, /ingest/text, /chat
│   │   ├── ingest.py    # URL / PDF / text -> chunks
│   │   ├── store.py     # tenant-aware Chroma vector store
│   │   ├── rag.py       # retrieve -> guardrail -> ground -> cite (the trust layer)
│   │   ├── config.py    # settings from env
│   │   └── schemas.py
│   ├── requirements.txt
│   └── .env.example
└── web/
    └── widget.html      # minimal tester (the real client widget comes later)
```

## Run it in ~5 minutes

```bash
cd backend
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt                       # first install pulls torch — a few hundred MB

cp .env.example .env
# edit .env and paste your key from console.anthropic.com (NOT your Claude Pro login)

uvicorn app.main:app --reload --port 8000
```

First request downloads the local embedding model (~80 MB) once.

## Try it

Feed it a real local business website, then ask questions:

```bash
# ingest a page (use a real business site, e.g. a local bakery or tutoring center)
curl -X POST http://localhost:8000/ingest/url \
  -H "Content-Type: application/json" \
  -d '{"tenant_id":"demo","url":"https://example-bakery.com/menu"}'

# ingest a PDF (price list, menu, policy doc)
curl -X POST http://localhost:8000/ingest/pdf \
  -F tenant_id=demo -F file=@/path/to/menu.pdf

# ask
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"tenant_id":"demo","question":"Do you have gluten-free options?"}'
```

Then open `web/widget.html` in a browser for a chat UI. Set the API to
`http://localhost:8000` and tenant to `demo`.

**The demo that sells:** ask one question whose answer IS on the site (it answers
with a citation) and one that ISN'T (it refuses and offers to connect you with the
team). Owners trust the second behavior more than the first.

---

## How to tune

- `MAX_DISTANCE` (in `.env`): lower = stricter grounding (refuses more, hallucinates
  less). Tune per client after testing real questions.
- `TOP_K`: how many chunks to retrieve.
- `CLAUDE_MODEL`: Sonnet 4.6 for quality; Haiku for cheaper/faster.

## Production notes (do NOT skip before a paying client)

- **Multi-tenancy is already wired** (one Chroma collection per `tenant_id`). Keep
  every client strictly separated.
- **Lock down CORS** in `main.py` to the client's domain.
- **Add auth** on the ingest endpoints (right now anyone who can reach them can
  upload). At minimum an API key per tenant.
- **Embeddings:** local model is fine for demos. For production retrieval quality,
  swap to Voyage AI (Anthropic's recommended embeddings). One function in `store.py`.
- **Don't white-label n8n.** When you add Phase 2, keep n8n as a hidden backend that
  *your* service calls — the customer-facing value stays in this code, which keeps
  you clear of n8n's commercial-license restrictions.

---

## Phase 2 (next, not built yet)

Once Phase 1 demos well and a client says yes, layer on:
1. **Tool use** — give Claude tools (`check_availability`, `book_slot`,
   `capture_order`, `send_summary`) so it can *act*, not just answer.
2. **Human-in-the-loop** — the bot drafts/queues the booking or order; the owner
   approves. (Owners want reliable, not autonomous.)
3. **Order summary + confirmation** back to the customer.
4. **Follow-up + feedback** — scheduled nudges, post-visit feedback capture.

n8n is the right place for the scheduled/queued plumbing in step 2–4. This RAG
service stays the brain.
