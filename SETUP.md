# Executive Assistant — Setup Guide

## What it does
- Voice conversation via OpenAI Realtime API (gpt-4o)
- Real-time web search (Tavily)
- Read/send Outlook email
- View/create Outlook calendar events
- Mobile-responsive PWA

## Prerequisites
- Python 3.10+
- Node.js 18+
- API keys (see below)

---

## 1. API Keys

### OpenAI
- Get key at https://platform.openai.com/api-keys
- Enable Realtime API access

### Tavily (web search)
- Free tier available at https://tavily.com
- Get key at https://app.tavily.com

### Azure (for Outlook)
1. Go to https://portal.azure.com → Azure Active Directory → App registrations → New registration
2. Name: "Executive Assistant"
3. Supported account types: "Accounts in any organizational directory and personal Microsoft accounts"
4. Redirect URI: `http://localhost:8000/auth/outlook/callback` (Web)
5. After creation, go to **Certificates & secrets** → New client secret → copy the Value
6. Note your **Application (client) ID** and **Directory (tenant) ID**
7. Go to **API permissions** → Add → Microsoft Graph → Delegated:
   - `Mail.ReadWrite`, `Mail.Send`, `Calendars.ReadWrite`, `User.Read`
   - Click **Grant admin consent**

---

## 2. Configure

```bash
cp backend/.env.example backend/.env
```

Fill in `backend/.env`:
```
OPENAI_API_KEY=sk-...
TAVILY_API_KEY=tvly-...
AZURE_CLIENT_ID=your-client-id
AZURE_CLIENT_SECRET=your-client-secret
AZURE_TENANT_ID=common
FRONTEND_URL=http://localhost:5173
```

---

## 3. Run

```bash
chmod +x start.sh
./start.sh
```

Then open http://localhost:5173

---

## 4. Connect Outlook

Click **"Connect Outlook"** in the top right of the app and sign in with your Microsoft account.

Tokens are stored per browser: the frontend keeps a random session id in
`localStorage` and the backend saves that session's Outlook tokens in a small
SQLite file (`backend/tokens.db`, override with `TOKEN_DB_PATH`). Access tokens
are refreshed automatically, so the connection survives both the one-hour token
lifetime and a backend restart. Clearing site data means reconnecting.

---

## 5. Health check

`GET /health` reports config and token-store state, returning 503 if anything
required is missing:

```bash
curl http://localhost:8000/health
curl "http://localhost:8000/health?deep=true"   # also verifies the OpenAI key live
```

---

## 6. Deploy to production

For production, you'll want to:
- Use a proper secret store (not .env)
- Mount a persistent disk and set `TOKEN_DB_PATH` to it, so Outlook logins survive redeploys
- Deploy backend on Railway/Render/Fly.io
- Deploy frontend on Vercel/Netlify
- Update `FRONTEND_URL` and Azure redirect URIs
