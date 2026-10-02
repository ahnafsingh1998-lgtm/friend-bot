Replace main.py completely with the code below. It uses Gemini, not Anthropic. Remove anthropic from requirements.txt (keep fastapi, uvicorn, httpx). The secret GEMINI_API_KEY is already set. Don't change anything else, then run the app.

import os

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response

VERIFY_TOKEN = os.environ["VERIFY_TOKEN"]
WA_TOKEN = os.environ["WHATSAPP_TOKEN"]
PHONE_ID = os.environ["WHATSAPP_PHONE_ID"]
GEMINI_KEY = os.environ["GEMINI_API_KEY"]
MODEL = "gemini-2.5-flash-lite"
MAX_MESSAGES = 40

SYSTEM = """You are the user's best friend, chatting over WhatsApp.

Style:
- Text like a real friend: casual, warm, short messages (1-3 sentences usually).
- Playful and funny when the mood fits; serious and present when it doesn't.
- Remember what they tell you in this chat and bring it up naturally.
- Ask about their life, but at most one question at a time.

Principles:
- You're an AI, and you never pretend to be human. If asked, say so plainly.
- Be honest like a good friend: tell them when you disagree, kindly.
- Encourage real-life friendships and connections; never try to make them
  dependent on you.
- If they seem to be in crisis or mention hurting themselves, respond with
  care, take it seriously, and encourage reaching out to a trusted person or
  local emergency/crisis services.
"""

app = FastAPI()
history: dict[str, list[dict]] = {}
seen_ids: set[str] = set()


@app.get("/")
async def home():
    return {"status": "friend bot is running"}


@app.get("/webhook")
async def verify(request: Request):
    q = request.query_params
    if q.get("hub.mode") == "subscribe" and q.get("hub.verify_token") == VERIFY_TOKEN:
        return Response(content=q.get("hub.challenge"), media_type="text/plain")
    raise HTTPException(status_code=403)


@app.post("/webhook")
async def receive(request: Request, tasks: BackgroundTasks):
    body = await request.json()
    try:
        msg = body["entry"][0]["changes"][0]["value"]["messages"][0]
    except (KeyError, IndexError):
        return {"ok": True}

    if msg["id"] in seen_ids:
        return {"ok": True}
    seen_ids.add(msg["id"])

    tasks.add_task(handle, msg)
    return {"ok": True}


async def handle(msg: dict):
    user = msg["from"]
    if msg.get("type") != "text":
        await send(user, "I can only read text for now, send me words :)")
        return

    chat = history.setdefault(user, [])
    chat.append({"role": "user", "parts": [{"text": msg["text"]["body"]}]})

    del chat[:-MAX_MESSAGES]
    while chat and chat[0]["role"] != "user":
        chat.pop(0)

    try:
        async with httpx.AsyncClient(timeout=60) as http:
            r = await http.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
                headers={"x-goog-api-key": GEMINI_KEY},
                json={
                    "systemInstruction": {"parts": [{"text": SYSTEM}]},
                    "contents": chat,
                    "generationConfig": {"maxOutputTokens": 400},
                },
            )
        r.raise_for_status()
        parts = r.json()["candidates"][0]["content"]["parts"]
        reply = "".join(p.get("text", "") for p in parts).strip()
        if not reply:
            raise ValueError("empty reply")
    except Exception as e:
        print("Gemini error:", e)
        chat.pop()
        await send(user, "Ugh, my brain glitched. Say that again?")
        return

    chat.append({"role": "model", "parts": [{"text": reply}]})
    await send(user, reply)


async def send(to: str, text: str):
    async with httpx.AsyncClient() as http:
        r = await http.post(
            f"https://graph.facebook.com/v21.0/{PHONE_ID}/messages",
            headers={"Authorization": f"Bearer {WA_TOKEN}"},
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": text},
            },
        )
        if r.status_code >= 400:
            print("WhatsApp send error:", r.text)
