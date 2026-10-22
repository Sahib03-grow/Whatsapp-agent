"""
WhatsApp Data Entry Agent
WhatsApp message -> Claude se fields nikalta hai -> Google Sheet mein row jodta hai -> WhatsApp par confirm karta hai.
"""
import asyncio
import json
import logging
import os
import re
from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo

import gspread
import httpx
from anthropic import AsyncAnthropic
from fastapi import BackgroundTasks, FastAPI, Query, Request, Response

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("agent")

# ---------- Settings (Railway Variables se aate hain) ----------
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "")
SHEET_ID = os.environ.get("SHEET_ID", "")
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
# Sirf in numbers ko allow karna hai (country code ke saath, bina +). Khali = sab allowed.
# Example: 916265215330,919999999999
ALLOWED_NUMBERS = {n.strip() for n in os.environ.get("ALLOWED_NUMBERS", "").split(",") if n.strip()}
MODEL = os.environ.get("MODEL", "claude-haiku-5-5")
GRAPH_VERSION = os.environ.get("GRAPH_VERSION", "v25.0")
TIMEZONE = ZoneInfo(os.environ.get("TIMEZONE", "Asia/Kolkata"))

# Sheet ke columns (is order mein row banegi). Badalna ho to yahan aur neeche build_row mein badlo.
COLUMNS = ["Date", "Naam", "Amount", "Type", "Note", "Phone", "Original message"]

app = FastAPI()
claude = AsyncAnthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None
seen_ids: deque = deque(maxlen=2000)  # Meta kabhi-kabhi same message dobara bhejta hai
_worksheet = None


# ---------- Google Sheet ----------
def get_worksheet():
    global _worksheet
    if _worksheet is None:
        gc = gspread.service_account_from_dict(json.loads(GOOGLE_SERVICE_ACCOUNT_JSON))
        _worksheet = gc.open_by_key(SHEET_ID).sheet1
    return _worksheet


def safe_cell(value):
    """Text '=' ya '+' se shuru ho to Sheet use formula na samjhe."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@"):
        return "'" + value
    return value


def append_rows(rows):
    ws = get_worksheet()
    if not ws.row_values(1):
        ws.insert_row(COLUMNS, 1)
    ws.append_rows(rows, value_input_option="USER_ENTERED")


# ---------- Claude se data nikalna ----------
def system_prompt():
    today = datetime.now(TIMEZONE).strftime("%Y-%m-%d (%A)")
    return f"""You extract data-entry records from WhatsApp messages written in Hindi, English or Hinglish.
Today's date is {today}.

Return ONLY a JSON object, nothing else, in this shape:
{{"entries": [{{"naam": string or null, "amount": number or null, "type": string or null, "note": string or null, "date": "YYYY-MM-DD"}}]}}

Rules:
- One entry per transaction. A message may contain several entries.
- "aaj" = today, "kal" = yesterday, "parso" = day before yesterday. If no date is given, use today.
- amount must be a plain number (no currency symbol, no commas).
- type is a short label such as cash, online, udhaar, jama, kharcha, etc., exactly as the user implies. null if not stated.
- note holds any extra detail. null if none.
- If the message is not a data entry (greeting, question, chatter), return {{"entries": []}}.
- Never invent values. Use null when something is missing."""


def parse_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("JSON nahi mila")
    return json.loads(text[start : end + 1])


async def extract_entries(message_text):
    resp = await claude.messages.create(
        model=MODEL,
        max_tokens=1000,
        system=system_prompt(),
        messages=[{"role": "user", "content": message_text}],
    )
    raw = "".join(block.text for block in resp.content if block.type == "text")
    return parse_json(raw).get("entries", [])


def build_row(entry, sender, original):
    return [
        safe_cell(entry.get("date") or datetime.now(TIMEZONE).strftime("%Y-%m-%d")),
        safe_cell(entry.get("naam") or ""),
        entry.get("amount"),
        safe_cell(entry.get("type") or ""),
        safe_cell(entry.get("note") or ""),
        safe_cell(sender),
        safe_cell(original),
    ]


# ---------- WhatsApp ----------
async def send_whatsapp(phone_number_id, to, text):
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{phone_number_id}/messages"
    payload = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text}}
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(url, json=payload, headers=headers)
        if r.status_code >= 400:
            log.error("WhatsApp send fail %s: %s", r.status_code, r.text)


async def handle_message(phone_number_id, sender, text):
    try:
        entries = await extract_entries(text)
        if not entries:
            await send_whatsapp(
                phone_number_id, sender,
                "Entry samajh nahi aayi. Is tarah bhejo:\nRamesh 5000 cash aaj",
            )
            return

        good = [e for e in entries if e.get("naam") and e.get("amount") is not None]
        bad = [e for e in entries if e not in good]

        if good:
            rows = [build_row(e, sender, text) for e in good]
            await asyncio.to_thread(append_rows, rows)

        lines = []
        for e in good:
            lines.append(f"✅ {e['naam']} | ₹{e['amount']} | {e.get('type') or '-'} | {e.get('date')}")
        if bad:
            lines.append(f"⚠️ {len(bad)} entry mein naam ya amount nahi mila. Wo dobara bhejo.")
        await send_whatsapp(phone_number_id, sender, "\n".join(lines))
    except Exception:
        log.exception("Message handle karte waqt error")
        await send_whatsapp(phone_number_id, sender, "Kuch gadbad ho gayi. Thodi der baad dobara bhejo.")


# ---------- Webhook ----------
@app.get("/")
async def health():
    return {"status": "ok"}


@app.get("/webhook")
async def verify(
    mode: str = Query(None, alias="hub.mode"),
    token: str = Query(None, alias="hub.verify_token"),
    challenge: str = Query(None, alias="hub.challenge"),
):
    if mode == "subscribe" and token == VERIFY_TOKEN and VERIFY_TOKEN:
        return Response(content=challenge, media_type="text/plain")
    return Response(status_code=403)


@app.post("/webhook")
async def receive(request: Request, background: BackgroundTasks):
    data = await request.json()
    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            phone_number_id = value.get("metadata", {}).get("phone_number_id")
            for msg in value.get("messages", []):
                msg_id, sender = msg.get("id"), msg.get("from")
                if msg_id in seen_ids:
                    continue
                seen_ids.append(msg_id)
                if ALLOWED_NUMBERS and sender not in ALLOWED_NUMBERS:
                    log.info("Ignored number: %s", sender)
                    continue
                if msg.get("type") != "text":
                    background.add_task(
                        send_whatsapp, phone_number_id, sender, "Abhi sirf text message samajh aate hain."
                    )
                    continue
                background.add_task(handle_message, phone_number_id, sender, msg["text"]["body"])
    return {"status": "received"}  # Meta ko turant 200 chahiye
