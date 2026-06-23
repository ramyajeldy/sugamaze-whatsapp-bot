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

SYSTEM_PROMPT = """You are a friendly WhatsApp assistant for a local business, answering customer FAQs.

STRICT RULES:
- Answer ONLY using information inside <context>. Do not use any outside knowledge.
- If the answer is not clearly in the context, reply EXACTLY:
  "I don't have that information, but I've let the team know — a team member will get back to you on this. Thank you for your patience!"
- Never invent or guess prices, hours, availability, policies, allergens, addresses, or contact details.
- Answer ONLY what was asked — no extra unrelated details, no filler greetings, no "let me know if you need anything else."
- Keep it short: 1-3 sentences unless the question genuinely needs a list (e.g. store hours, multiple menu items).
- Warm and natural tone, like a quick WhatsApp reply — not a customer-service script.
- Do not show citation brackets like [1] to the customer — citations are for the website widget only.
- Formatting is for WhatsApp, not Markdown: use *single asterisks* for bold (never **double**), and avoid headers or tables.
"""

ESCALATION = (
    "I don't have that information, but I've let the team know — a team "
    "member will get back to you on this. Thank you for your patience!"
)


def _build_context(hits):
    blocks, sources = [], []
    for i, h in enumerate(hits, start=1):
        meta = h.get("metadata") or {}
        blocks.append(f"[{i}] (from {meta.get('title', 'source')}):\n{h['text']}")
        sources.append(
            {"n": i, "source": meta.get("source"), "title": meta.get("title")}
        )
    return "\n\n".join(blocks), sources


def answer(tenant_id, question, customer_phone: str = None):
    # Handle simple greetings and thank yous
    q_lower = question.lower().strip()

    if q_lower in {"hi", "hello", "hey", "hello!", "hi!", "hey!"}:
        return {
            "answer": "Hi there! 👋 Welcome to Sugamaze. How can I help you with our cakes today?",
            "grounded": True,
            "sources": []
        }

    if q_lower in {"thanks", "thank you", "thanks!"}:
        return {
            "answer": "Thank you for reaching out to Sugamaze! Enjoy your sweet treat 😊",
            "grounded": True,
            "sources": []
        }

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

    # Trigger menu if "menu" appears anywhere in the question
    if "menu" in q_lower:
        menu_text = """✨ *Sugamaze Menu* ✨

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
        return {
            "answer": menu_text,
            "grounded": True,
            "sources": []
        }

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
