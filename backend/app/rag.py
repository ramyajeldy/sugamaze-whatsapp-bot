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
from . import store, notify

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
- Never truncate or abbreviate a phone number, address, price, or any
  other concrete detail mid-way — always state it in full, exactly as
  given in <context>.
- If the answer isn't clearly supported by <context>, you MUST reply
  EXACTLY:
  "I don't have that information, but I've let the team know — a team member will get back to you on this. Thank you for your patience!"
  Do not soften, guess, or partially answer instead.

## Tone & Style
- Warm, soft, friendly — like a helpful person texting back, not a
  corporate script. Never robotic, never stiff.
- Keep replies short and to the point: 1-3 sentences unless the question
  truly needs a list (hours, menu items).
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

# The one true sign-off — used only when a conversation is genuinely
# ending (customer says thanks/bye, or declines to keep chatting), never
# appended after a regular FAQ answer.
CLOSING_LINE = "Thank you for contacting Sugamaze! Hope to see you around soon 🙂"

TEAM_ESCALATION_LINE = "A team member will reach out to you soon. Thank you for your patience."

ORDER_TEXT = (
    "Please leave your name, order details, date required, and "
    "upload any design ideas, and my team will get back to you "
    "with pricing and order confirmation during our business "
    "hours 😊\n\nThank you for choosing Sugamaze 💕"
)

LOCATION_TEXT = "We're located at *30 St Thomas St, Whitby, ON L1M 1H1* (Durham Region, Ontario). 📍"

HOURS_TEXT = (
    "🕐 *Monday:* 11:00 am – 8:00 pm\n"
    "❌ *Tuesday:* Closed\n"
    "🕐 *Wednesday – Friday:* 11:00 am – 8:00 pm\n"
    "🕐 *Saturday & Sunday:* 10:00 am – 9:00 pm"
)

MENU_TEXT = """✨ *Sugamaze Menu* ✨

*Custom Cakes* (all 100% eggless):
• Wedding cakes (tiered)
• Birthday cakes (custom designs)
• Anniversary cakes
• Gender reveal cakes
• Photo cakes (edible printed images)
• Graduation cakes
• Valentine cakes
• Theme-based cakes
• Sweet 16 cakes

*Ready-to-Eat Cakes:*
• Ready-to-go cakes (fresh, great for last-minute celebrations!)

*Individual Treats:*
• Dessert cups — $4.00
• Cupcakes
• Cake pops
• Macaroons — $12.00
• Patties/Puffs

💕 Every cake is handcrafted with love! Custom cakes are quoted based on size, design & flavour.

Ready to place your order? Call us at *+1 (905) 655-7878* or visit sugamaze.ca/contact-us — let's make your celebration sweet! 🎂✨"""


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


def answer(tenant_id, question, customer_phone: str = None):
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
            "answer": CLOSING_LINE,
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
        return {"answer": ORDER_TEXT, "grounded": True, "sources": []}

    # Escalate any allergy-related questions to shop owner (safety critical)
    allergy_keywords = {"allerg", "vegan", "gluten", "dairy", "nuts", "nut-free", "egg-free", "lactose", "celiac", "intolerant", "sensitivity"}
    if any(keyword in q_lower for keyword in allergy_keywords):
        if customer_phone:
            notify.notify_escalation(customer_phone, question)
        return {
            "answer": ESCALATION,
            "grounded": False,
            "sources": []
        }

    # Always give the exact address for any location-related phrasing —
    # too important to leave to retrieval/generation variance.
    location_keywords = {"located", "location", "address"}
    where_phrases = {"where are you", "where is sugamaze", "where is your store",
                      "where is your shop", "where can i find you", "find your store"}
    if any(k in q_lower for k in location_keywords) or any(p in q_lower for p in where_phrases):
        return {"answer": LOCATION_TEXT, "grounded": True, "sources": []}

    # Always give the exact hours for any hours-related phrasing — same
    # reasoning as location: too important to leave to retrieval variance.
    hours_keywords = {"hours", "open", "close", "closing", "opening"}
    if any(k in q_lower for k in hours_keywords):
        return {"answer": HOURS_TEXT, "grounded": True, "sources": []}

    # Trigger menu if "menu" appears anywhere in the question
    if "menu" in q_lower:
        return {"answer": MENU_TEXT, "grounded": True, "sources": []}

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
    msg = _client.messages.create(
        model=_settings.claude_model,
        max_tokens=600,
        temperature=0.2,  # precise FAQ answers, not creative writing — avoid random slip-ups (e.g. truncated phone numbers)
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"<context>\n{context}\n</context>\n\nCustomer question: {question}",
            }
        ],
    )
    text = "".join(b.text for b in msg.content if b.type == "text").strip()

    # If Claude returned the escalation message, notify the shop owner
    if text.startswith("I don't have that information") and customer_phone:
        notify.notify_escalation(customer_phone, question)

    return {"answer": text, "grounded": True, "sources": sources}
