"""
The grounded-answering core. This is the part that makes the bot trustworthy
enough for a nervous business owner to put in front of customers:

1. Deterministic shortcuts: a small set of tenant-defined keyword categories
   (hours, location, allergy/safety, etc.) always get a fixed, reviewed
   answer instead of being left to retrieval/generation variance.
2. Retrieve the most relevant chunks for anything else.
3. GUARDRAIL: drop weak matches. If nothing survives, refuse WITHOUT calling
   Claude — guaranteeing no hallucinated price/hours/policy and saving cost.
4. Otherwise, give Claude ONLY the retrieved context and a strict instruction
   to answer from it alone, cite sources, and escalate when unsure.

This retrieve -> guardrail -> ground -> cite pattern is generic and shared
across every tenant (BASE_GROUNDING_RULES below); only the identity, tone,
topic guardrail, and shortcut categories vary per tenant.
"""
from functools import lru_cache

from anthropic import Anthropic

from .config import get_settings
from .tenants import TenantConfig, get_tenant
from . import store, notify, admin_settings, usage

_settings = get_settings()
_client = Anthropic(api_key=_settings.anthropic_api_key)

# The generic retrieve -> guardrail -> ground -> escalate rules, shared by
# every tenant regardless of vertical. Tenant-specific identity/tone/topic
# text is spliced in around this in _build_system_prompt().
BASE_GROUNDING_RULES = """## Core Principle: Grounded, Never Guessing
- Answer ONLY using the information given to you in <context>. Never use
  outside knowledge, training data, or assumptions about the business.
- Never invent or estimate: prices, availability, policies, deadlines,
  timelines, or any commitment on the business's behalf.
- If two pieces of context disagree or one is vague and one is specific,
  always prefer the more specific, concrete one.
- Do not extrapolate: if <context> answers a question about something
  similar but different from what was asked, that is NOT the same as
  having the answer. Escalate instead of assuming it transfers.
- When context contains a Q&A pair whose question directly matches what the
  customer asked, reproduce the answer faithfully — do not rephrase, shorten,
  or rewrite it.
- Never truncate or abbreviate a phone number, address, price, date, or any
  other concrete detail mid-way — always state it in full, exactly as
  given in <context>.
- If the answer isn't clearly supported by <context>, you MUST reply
  EXACTLY:
  "{escalation_text}"
  Do not soften, guess, or partially answer instead.

## Answer Length Calibration
- Match the answer length exactly to what was asked. A yes/no question
  gets one sentence. A "how do I…" gets the full steps. A list question
  gets a brief list — nothing more.
- Never pad an answer with background information the customer didn't ask
  for. Never cut a multi-part answer short.
- When the context contains a Q&A pair that directly matches the question,
  give that answer in full — do not summarise or trim it.
- Whenever you direct someone to contact the team for anything you can't
  handle yourself, always include the full contact details given to you
  below in your reply — never abbreviate them.
  Phone: {contact_phone}
  Email: {contact_email}

## Tone & Style
- Warm, soft, friendly — like a helpful person texting back, not a
  corporate script. Never robotic, never stiff.
- Keep replies conversational: short for simple questions, complete for
  detailed ones — never cut off mid-answer and never over-explain.
- Use pleasant, cool emojis sparingly and only where they naturally fit —
  never more than 1-2 per message, never forced.
- No slang that feels out of place, no overly casual abbreviations.
- NEVER use harsh, sarcastic, dismissive, or inappropriate language — even
  if the customer is rude or impatient. Stay kind regardless.
- No filler like "let me know if you need anything else" — answer only
  what was asked.

## Never Leave a Customer in a Dilemma
- Every reply must give the customer a clear next step — either a direct
  answer, or a clear, reassuring path forward (e.g. "I've let the team
  know, they'll reach out shortly").
- Never respond with uncertainty that leaves the customer unsure what to
  do next (avoid "maybe," "I think," "not sure, you could try..."). Be
  decisive: either you know, or you escalate cleanly.

## Boundaries on What You Can Promise
- You cannot place orders/bookings, take payments, confirm dates, or make
  policy exceptions — you can only inform and direct the customer to
  contact the team for anything that requires committing the business.
- Never claim something is "guaranteed," "definitely possible," or "no
  problem" for anything outside your given context — only the team can
  make those calls.
- If asked whether you're a bot/AI, answer honestly and warmly — never
  pretend to be a human.

## Using Conversation History
- You may be shown a few recent turns before the current question. Use them
  ONLY to resolve what the customer is referring to (e.g. "that one," "how
  much is it") — never as a source of facts.
- The <context> given for the CURRENT question is the only place you may
  pull prices, policies, or other concrete details from — even if an
  earlier turn already stated something similar. If the current <context>
  doesn't cover what's being asked about, escalate; do not answer from
  memory of an earlier turn.

## When to Ask for Clarification vs. When to Escalate
These are two different situations — do not confuse them:

1. **The customer's question is ambiguous** (the right answer depends on a
   detail they haven't given). Here, ask ONE short, friendly clarifying
   question before answering. One question at a time, never a list. Only
   ask when the answer would genuinely change — if <context> already
   covers it, just answer.

2. **The context is missing, incomplete, or doesn't clearly cover what was
   asked** (not a wording problem — the information itself isn't there).
   Here you do NOT ask a clarifying question and you do NOT guess or fill
   the gap with anything that sounds plausible. Give the exact escalation
   reply defined above. A confident-sounding guess is worse than admitting
   you don't know — it's the one failure mode that damages trust in this
   bot completely.

Never do the following under any circumstance: extrapolate a price,
timeline, or policy from a similar-but-different item in <context>;
average or estimate between two numbers you were given; state something as
fact because it seems reasonable for a business like this to offer.

## Formatting (WhatsApp-specific)
- Use *single asterisks* for bold — never **double** (that's Markdown, not
  WhatsApp).
- No headers, no tables, no citation brackets like [1] — this is a chat
  message, not a document."""


@lru_cache(maxsize=None)
def _build_system_prompt(tenant_id: str) -> str:
    tenant = get_tenant(tenant_id)
    grounding = BASE_GROUNDING_RULES.format(
        escalation_text=tenant.escalation_text,
        contact_phone=tenant.contact_phone,
        contact_email=tenant.contact_email,
    )
    return (
        f"# {tenant.business_name} WhatsApp Assistant — System Prompt\n\n"
        f"## Identity\n{tenant.identity_block}\n\n"
        f"{grounding}\n\n"
        f"## Topic Guardrails\n{tenant.topic_guardrail}"
    )


def CLOSING_LINE(tenant_id: str):
    return admin_settings.get_message(tenant_id, "closing_line")


def _build_context(hits):
    blocks, sources = [], []
    for i, h in enumerate(hits, start=1):
        meta = h.get("metadata") or {}
        blocks.append(f"[{i}] (from {meta.get('title', 'source')}):\n{h['text']}")
        sources.append(
            {"n": i, "source": meta.get("source"), "title": meta.get("title")}
        )
    return "\n\n".join(blocks), sources


def is_greeting(tenant_id: str, question: str) -> bool:
    tenant = get_tenant(tenant_id)
    return question.lower().strip() in {g.lower() for g in tenant.greetings}


def _match_shortcut(tenant: TenantConfig, q_lower: str) -> dict | None:
    for rule in tenant.shortcuts:
        if any(kw in q_lower for kw in rule["keywords"]):
            return rule
    return None


def _apply_shortcut(tenant: TenantConfig, rule: dict, question: str, customer_phone: str | None):
    text = admin_settings.get_message(tenant.tenant_id, rule["response_key"])
    notify_type = rule.get("notify")
    if customer_phone and notify_type == "priority_lead":
        notify.notify_priority_lead(tenant, customer_phone, rule.get("notify_label", rule["response_key"]))
    elif customer_phone and notify_type == "escalation":
        notify.notify_escalation(tenant, customer_phone, question)
    return {"answer": text, "grounded": rule.get("grounded", True), "sources": []}


def answer(tenant_id, question, customer_phone: str = None, history: list = None):
    tenant = get_tenant(tenant_id)
    q_lower = question.lower().strip()

    if q_lower in {g.lower() for g in tenant.greetings}:
        return {
            "answer": admin_settings.get_message(tenant_id, "greeting_reply")
            or f"Hi there! 👋 Welcome to {tenant.business_name}. How can I help you today?",
            "grounded": True,
            "sources": [],
        }

    if q_lower in {c.lower() for c in tenant.closing_phrases}:
        return {"answer": CLOSING_LINE(tenant_id), "grounded": True, "sources": []}

    rule = _match_shortcut(tenant, q_lower)
    if rule is not None:
        return _apply_shortcut(tenant, rule, question, customer_phone)

    hits = store.query(tenant_id, question, _settings.top_k)

    # Guardrail: keep only sufficiently-similar chunks.
    hits = [
        h for h in hits
        if h.get("distance") is None or h["distance"] <= _settings.max_distance
    ]

    if not hits:
        if customer_phone:
            notify.notify_escalation(tenant, customer_phone, question)
        return {"answer": tenant.escalation_text, "grounded": False, "sources": []}

    context, sources = _build_context(hits)
    messages = list(history) if history else []
    messages.append({
        "role": "user",
        "content": f"<context>\n{context}\n</context>\n\nCustomer question: {question}",
    })
    msg = _client.messages.create(
        model=_settings.claude_model,
        max_tokens=600,
        temperature=0.2,  # precise FAQ answers, not creative writing — avoid random slip-ups (e.g. truncated phone numbers)
        system=_build_system_prompt(tenant_id),
        messages=messages,
    )
    text = "".join(b.text for b in msg.content if b.type == "text").strip()
    usage.record_claude_call(tenant_id, msg.usage.input_tokens, msg.usage.output_tokens)

    # If Claude returned the escalation message, notify the shop owner
    if text.startswith(tenant.escalation_text[:40]) and customer_phone:
        notify.notify_escalation(tenant, customer_phone, question)

    return {"answer": text, "grounded": True, "sources": sources}
