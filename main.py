import os, json, sqlite3
import httpx
from fastapi import FastAPI, Request, Response, BackgroundTasks
from anthropic import Anthropic

app = FastAPI()
claude = Anthropic()  # ANTHROPIC_API_KEY env se leta hai
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "change-me")
DEFAULT_WA_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")
HANDOFF_WORDS = ["human", "insaan", "agent", "manager", "baat karni", "call me"]

# Har client (business) ka alag config. Key = WhatsApp phone_number_id
with open("clients.json", encoding="utf-8") as f:
    CLIENTS = json.load(f)

db = sqlite3.connect("chats.db", check_same_thread=False)
db.execute("CREATE TABLE IF NOT EXISTS msgs (id INTEGER PRIMARY KEY, biz TEXT, cust TEXT, role TEXT, text TEXT)")
db.execute("CREATE TABLE IF NOT EXISTS handoff (biz TEXT, cust TEXT, PRIMARY KEY (biz, cust))")
db.commit()


def send_wa(pnid, to, text, client):
    token = client.get("token") or DEFAULT_WA_TOKEN
    httpx.post(
        f"https://graph.facebook.com/v21.0/{pnid}/messages",
        headers={"Authorization": f"Bearer {token}"},
        json={"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text}},
        timeout=20,
    )


def save(biz, cust, role, text):
    db.execute("INSERT INTO msgs (biz, cust, role, text) VALUES (?,?,?,?)", (biz, cust, role, text))
    db.commit()


def history(biz, cust, n=10):
    rows = db.execute(
        "SELECT role, text FROM msgs WHERE biz=? AND cust=? ORDER BY id DESC LIMIT ?", (biz, cust, n)
    ).fetchall()[::-1]
    while rows and rows[0][0] != "user":  # Claude ko pehla message user ka chahiye
        rows.pop(0)
    return [{"role": r, "content": t} for r, t in rows]


def process(pnid, cust, text):
    client = CLIENTS.get(pnid)
    if not client:
        return
    if db.execute("SELECT 1 FROM handoff WHERE biz=? AND cust=?", (pnid, cust)).fetchone():
        return  # human sambhal raha hai, bot chup

    first = db.execute("SELECT 1 FROM msgs WHERE biz=? AND cust=?", (pnid, cust)).fetchone() is None

    # 1) Pehla message: greeting
    if first:
        save(pnid, cust, "user", text)
        greeting = client["greeting"]
        save(pnid, cust, "assistant", greeting)
        send_wa(pnid, cust, greeting, client)
        return

    # 2) Human handoff
    if any(w in text.lower() for w in HANDOFF_WORDS):
        db.execute("INSERT OR IGNORE INTO handoff VALUES (?,?)", (pnid, cust))
        db.commit()
        send_wa(pnid, cust, "Theek hai, hamari team aapse jaldi baat karegi. 🙏", client)
        if client.get("owner_number"):
            send_wa(pnid, client["owner_number"], f"Customer {cust} human se baat karna chahta hai.\nLast msg: {text}", client)
        return

    # 3) AI reply
    save(pnid, cust, "user", text)
    try:
        resp = claude.messages.create(
            model=MODEL,
            max_tokens=400,
            system=client["system_prompt"],
            messages=history(pnid, cust),
        )
        reply = resp.content[0].text
    except Exception as e:
        print("Claude error:", e)
        reply = "Maaf kijiye, abhi kuch technical dikkat hai. Hamari team jaldi reply karegi."
    save(pnid, cust, "assistant", reply)
    send_wa(pnid, cust, reply, client)


@app.get("/webhook")
def verify(request: Request):
    p = request.query_params
    if p.get("hub.mode") == "subscribe" and p.get("hub.verify_token") == VERIFY_TOKEN:
        return Response(content=p.get("hub.challenge"), media_type="text/plain")
    return Response(status_code=403)


@app.post("/webhook")
async def incoming(request: Request, bg: BackgroundTasks):
    data = await request.json()
    for entry in data.get("entry", []):
        for ch in entry.get("changes", []):
            v = ch.get("value", {})
            pnid = v.get("metadata", {}).get("phone_number_id")
            for m in v.get("messages", []):
                if m.get("type") == "text":
                    bg.add_task(process, pnid, m["from"], m["text"]["body"])
    return {"status": "ok"}


@app.get("/")
def health():
    return {"status": "running"}
