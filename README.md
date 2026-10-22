# WhatsApp AI Agent (multi-client)

## Run karna
1. `pip install -r requirements.txt`
2. `.env.example` ko copy karke keys bharo, phir load karo:
   `export $(cat .env | xargs)`
3. `clients.json` mein apne client ka phone_number_id, greeting aur system_prompt daalo.
4. `uvicorn main:app --host 0.0.0.0 --port 8000`

## Meta setup
1. developers.facebook.com par App banao (type: Business), WhatsApp product add karo.
2. WhatsApp > API Setup se `Phone number ID` aur temporary token lo (permanent token ke liye System User banao).
3. Server ko internet par chalao (test ke liye `ngrok http 8000`, production ke liye Railway/Render).
4. WhatsApp > Configuration > Webhook:
   - Callback URL: `https://tumhara-domain/webhook`
   - Verify token: wahi jo `.env` mein VERIFY_TOKEN hai
   - `messages` field subscribe karo.
5. Test number par message bhejo.

## Naya client add karna
`clients.json` mein ek aur block daalo (uska phone_number_id key banega) aur server restart karo.

## Kaise kaam karta hai
- Pehla message: greeting ("aapko kya kaam hai?")
- Uske baad: Claude AI client ke prompt ke hisaab se jawab deta hai
- Customer "human / manager / insaan" likhe to bot band, owner ko alert
