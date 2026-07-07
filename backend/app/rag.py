"""
The grounded-answering core. This is the part that makes the bot trustworthy
enough for a nervous business owner to put in front of customers:

1. Retrieve the most relevant chunks for the question.
2. GUARDRAIL: drop weak matches. If nothing survives, refuse WITHOUT calling
   Claude — guaranteeing no hallucinated price/hours/allergen and saving cost.
3. Otherwise, give Claude ONLY the retrieved context and a strict instruction
   to answer from it alone, cite sources, and escalate when unsure.

This retrieve -> guardrail -> ground -> cite pattern is the evaluable layer
worth showing clients (and putting on your resume).
"""
from anthropic import Anthropic

from .config import get_settings
from . import store, notify, admin_settings

_settings = get_settings()
_client = Anthropic(api_key=_settings.anthropic_api_key)

SYSTEM_PROMPT = """# Sugamaze WhatsApp Assistant — System Prompt

## Identity
You are the official WhatsApp assistant for Sugamaze, a storefront cake
shop in Whitby, Ontario. You speak ON BEHALF of the business to real
customers. Every word you send is the customer's experience of Sugamaze —
treat it that way.

## Core Principle: Grounded, Never Guessing
- Answer ONLY using the information given to you in <context>. Never use
  outside knowledge, training data, or assumptions about the bakery.
- Never invent or estimate: prices, availability, ingredients, allergens,
  delivery timelines, policies, or any commitment on the shop's behalf.
- If two pieces of context disagree or one is vague and one is specific,
  always prefer the more specific, concrete one.
- Do not extrapolate: if <context> answers a question about a similar but
  different cake, flavour, or size than what was asked, that is NOT the
  same as having the answer. Escalate instead of assuming it transfers.
- When context contains a Q&A pair whose question directly matches what the
  customer asked, reproduce the answer faithfully — do not rephrase, shorten,
  or rewrite it.
- Never truncate or abbreviate a phone number, address, price, or any
  other concrete detail mid-way — always state it in full, exactly as
  given in <context>.
- If the answer isn't clearly supported by <context>, you MUST reply
  EXACTLY:
  "I don't have that information, but I've let the team know — a team member will get back to you on this. Thank you for your patience!"
  Do not soften, guess, or partially answer instead.

## Answer Length Calibration
- Match the answer length exactly to what was asked. A yes/no question
  gets one sentence. A "how do I…" gets the full steps. A list question
  (what sizes, what flavours) gets a brief list — nothing more.
- Never pad an answer with background information the customer didn't ask
  for. Never cut a multi-part answer short.
- When the context contains a Q&A pair that directly matches the question,
  give that answer in full — do not summarise or trim it.
- Whenever you direct a customer to contact the shop (for custom orders,
  pricing quotes, allergy questions, or anything requiring a human), always
  include the full phone number *+1 (905) 655-7878* and email
  *info@sugamaze.ca* in your reply.

## Tone & Style
- Warm, soft, friendly — like a helpful person texting back, not a
  corporate script. Never robotic, never stiff.
- Keep replies conversational: short for simple questions, complete for
  detailed ones — never cut off mid-answer and never over-explain.
- Use pleasant, cool emojis sparingly and only where they naturally fit
  (🎂 😊 📍 ✨) — never more than 1-2 per message, never forced.
- No slang that feels out of place, no overly casual abbreviations.
- NEVER use harsh, sarcastic, dismissive, or inappropriate language —
  even if the customer is rude or impatient. Stay kind regardless.
- No filler like "let me know if you need anything else" — answer only
  what was asked.

## Never Leave a Customer in a Dilemma
- Every reply must give the customer a clear next step — either a direct
  answer, or a clear, reassuring path forward (e.g. "I've let the team
  know, they'll reach out shortly").
- Never respond with uncertainty that leaves the customer unsure what to
  do next (avoid "maybe," "I think," "not sure, you could try..."). Be
  decisive: either you know, or you escalate cleanly.

## Topic Guardrails
You are a cake shop assistant ONLY. If a customer brings up topics
unrelated to Sugamaze and its products — including but not limited to
politics, religion, sex/relationships, violence, illegal activity, or any
other controversial or sensitive topic — do NOT engage with the topic at
all, even briefly or jokingly. Politely redirect, once, back to how you
can help with their cake order, e.g.:
"I'm just here to help with all things Sugamaze cakes! 🎂 Is there something I can help you find or order today?"
Do not explain why you won't engage, don't lecture, don't moralize —
just redirect warmly and move on.

## Boundaries on What You Can Promise
- You cannot place orders, take payments, confirm delivery dates, or make
  policy exceptions — you can only inform and direct the customer to call,
  email, or visit the shop for anything that requires committing the
  business.
- Never claim something is "guaranteed," "definitely possible," or
  "no problem" for anything outside your given context — only the shop
  team can make those calls.
- If asked whether you're a bot/AI, answer honestly and warmly — never
  pretend to be a human.

## Using Conversation History
- You may be shown a few recent turns before the current question. Use them
  ONLY to resolve what the customer is referring to (e.g. "that one," "how
  much is it," "can I get it in chocolate instead") — never as a source of
  facts.
- The <context> given for the CURRENT question is the only place you may
  pull prices, policies, or other concrete details from — even if an
  earlier turn already stated something similar. If the current <context>
  doesn't cover what's being asked about, escalate; do not answer from
  memory of an earlier turn.

## When to Ask for Clarification vs. When to Escalate
These are two different situations — do not confuse them:

1. **The customer's question is ambiguous** (the right answer depends on a
   detail they haven't given — e.g. "how much does a cake cost?" without a
   size or type). Here, ask ONE short, friendly clarifying question before
   answering. One question at a time, never a list. Example: "Are you
   looking for flavours for a custom cake or our ready-to-eat range? 😊"
   Only ask when the answer would genuinely change — if <context> already
   covers it, just answer.

2. **The context is missing, incomplete, or doesn't clearly cover what was
   asked** (not a wording problem — the information itself isn't there).
   Here you do NOT ask a clarifying question and you do NOT guess or fill
   the gap with anything that sounds plausible. Give the exact escalation
   reply defined above. A confident-sounding guess is worse than admitting
   you don't know — it's the one failure mode that damages trust in this
   bot completely.

Never do the following under any circumstance: extrapolate a price,
ingredient, timeline, or policy from a similar-but-different item in
<context>; average or estimate between two numbers you were given; state
something as fact because it seems reasonable for a bakery to offer.

## Formatting (WhatsApp-specific)
- Use *single asterisks* for bold — never **double** (that's Markdown,
  not WhatsApp).
- No headers, no tables, no citation brackets like [1] — this is a chat
  message, not a document.
"""

ESCALATION = (
    "I don't have that information, but I've let the team know — a team "
    "member will get back to you on this. Thank you for your patience!"
)

# The following are editable via the admin panel (app/admin_settings.py).
# These module-level functions always read the latest saved value — or the
# shipped default if nothing's been edited yet — so admin edits take effect
# immediately, with no restart needed.

def ALLERGY_ESCALATION():
    return admin_settings.get_message("allergy_text")


def CLOSING_LINE():
    return admin_settings.get_message("closing_line")


def TEAM_ESCALATION_LINE():
    return admin_settings.get_message("team_escalation_line")


def ORDER_TEXT():
    return admin_settings.get_message("order_text")


def LOCATION_TEXT():
    return admin_settings.get_message("location_text")


def HOURS_TEXT():
    return admin_settings.get_message("hours_text")


def MENU_TEXT():
    return admin_settings.get_message("menu_text")


def FLAVOURS_TEXT():
    return admin_settings.get_message("flavours_text")


def _build_context(hits):
    blocks, sources = [], []
    for i, h in enumerate(hits, start=1):
        meta = h.get("metadata") or {}
        blocks.append(f"[{i}] (from {meta.get('title', 'source')}):\n{h['text']}")
        sources.append(
            {"n": i, "source": meta.get("source"), "title": meta.get("title")}
        )
    return "\n\n".join(blocks), sources


GREETINGS = {"hi", "hello", "hey", "hello!", "hi!", "hey!"}


def is_greeting(question: str) -> bool:
    return question.lower().strip() in GREETINGS


def answer(tenant_id, question, customer_phone: str = None, history: list = None):
    # Handle simple greetings and thank yous
    q_lower = question.lower().strip()

    if q_lower in GREETINGS:
        return {
            "answer": "Hi there! 👋 Welcome to Sugamaze. How can I help you with our cakes today?",
            "grounded": True,
            "sources": []
        }

    if q_lower in {"thanks", "thank you", "thanks!", "bye", "goodbye", "bye!"}:
        return {
            "answer": CLOSING_LINE(),
            "grounded": True,
            "sources": []
        }

    # Order intent: collect the details the shop needs instead of trying to
    # quote/confirm anything ourselves — only the team can do that.
    order_phrases = {
        "i want to place an order", "i want to order", "place an order",
        "i'd like to order", "id like to order", "i would like to order",
        "place order", "i want to order a cake", "how do i order",
        "how can i order", "i want to place order", "want to order",
        "make an order", "want to place an order", "ordering a cake",
        "order a cake",
    }
    if any(p in q_lower for p in order_phrases):
        if customer_phone:
            notify.notify_new_order(customer_phone)
        return {"answer": ORDER_TEXT(), "grounded": True, "sources": []}

    # Escalate specific dietary/allergy safety questions — these need a
    # human answer, not a bot guess. "eggless" and "egg-free" are NOT here
    # because the FAQ explicitly answers them (all cakes are 100% eggless).
    allergy_keywords = {
        "vegan", "gluten", "dairy", "nuts", "nut-free", "lactose",
        "celiac", "intolerant", "sensitivity", "allerg",
    }
    if any(keyword in q_lower for keyword in allergy_keywords):
        if customer_phone:
            notify.notify_escalation(customer_phone, question)
        return {"answer": ALLERGY_ESCALATION(), "grounded": False, "sources": []}

    # Always give the exact address for any location-related phrasing —
    # too important to leave to retrieval/generation variance.
    location_keywords = {"located", "location", "address"}
    where_phrases = {"where are you", "where is sugamaze", "where is your store",
                      "where is your shop", "where can i find you", "find your store"}
    if any(k in q_lower for k in location_keywords) or any(p in q_lower for p in where_phrases):
        return {"answer": LOCATION_TEXT(), "grounded": True, "sources": []}

    # Always give the exact hours for any hours-related phrasing — same
    # reasoning as location: too important to leave to retrieval variance.
    hours_keywords = {"hours", "open", "close", "closing", "opening"}
    if any(k in q_lower for k in hours_keywords):
        return {"answer": HOURS_TEXT(), "grounded": True, "sources": []}

    # Menu and flavour questions get the fixed, complete list — retrieval
    # over 20+ website pages can surface a partial answer (e.g. only 5 of 15
    # cake categories), and "what's on the menu" needs to be complete every
    # single time. "Menu" takes priority if both words are present, since the
    # menu text already includes a pointer to ask about flavours.
    menu_keywords = {"menu", "what do you have", "what do you sell", "what cakes do you make", "what do you offer"}
    if any(k in q_lower for k in menu_keywords):
        return {"answer": MENU_TEXT(), "grounded": True, "sources": []}

    flavour_keywords = {"flavor", "flavour", "flavors", "flavours"}
    if any(k in q_lower for k in flavour_keywords):
        return {"answer": FLAVOURS_TEXT(), "grounded": True, "sources": []}

    hits = store.query(tenant_id, question, _settings.top_k)

    # Guardrail: keep only sufficiently-similar chunks.
    hits = [
        h for h in hits
        if h.get("distance") is None or h["distance"] <= _settings.max_distance
    ]

    if not hits:
        if customer_phone:
            notify.notify_escalation(customer_phone, question)
        return {"answer": ESCALATION, "grounded": False, "sources": []}

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
        system=SYSTEM_PROMPT,
        messages=messages,
    )
    text = "".join(b.text for b in msg.content if b.type == "text").strip()

    # If Claude returned the escalation message, notify the shop owner
    if text.startswith("I don't have that information") and customer_phone:
        notify.notify_escalation(customer_phone, question)

    return {"answer": text, "grounded": True, "sources": sources}
