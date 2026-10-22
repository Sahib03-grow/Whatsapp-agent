# WhatsApp Data Entry Agent

WhatsApp par message bhejo -> Claude fields nikalta hai -> Google Sheet mein row jud jaati hai -> WhatsApp par confirm aata hai.

Example message: `Ramesh 5000 cash aaj`

## Railway Variables
| Variable | Kya daalna hai |
|---|---|
| ANTHROPIC_API_KEY | console.anthropic.com ki key |
| WHATSAPP_TOKEN | Meta ka access token |
| VERIFY_TOKEN | Aapka khud ka secret shabd (Meta mein bhi wahi) |
| SHEET_ID | Google Sheet ke URL mein /d/ aur /edit ke beech ka hissa |
| GOOGLE_SERVICE_ACCOUNT_JSON | Service account ki JSON file ka poora content |
| ALLOWED_NUMBERS | (Zaroori) Sirf aapke numbers, jaise 916265215330 |

## Start Command
uvicorn main:app --host 0.0.0.0 --port $PORT

## Sheet ke columns
Date, Naam, Amount, Type, Note, Phone, Original message
(Header row bot khud bana deta hai.)
