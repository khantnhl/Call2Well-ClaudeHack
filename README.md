# ClearPath

> "We don't just find the clinic — we connect the call."

ClearPath is a voice-based AI navigator for the 27 million uninsured Americans who can't afford a doctor. Call a number, describe your situation in plain language, and ClearPath finds the best free clinic near you — then connects the call directly.

No app. No typing. No insurance jargon. Just call.

## How It Works

1. **Call** the ClearPath number
2. **Describe** your situation in any language
3. **Claude** triages urgency, checks eligibility, finds best-matched clinic
4. **Choose** to connect directly or receive clinic details by text

## Tech Stack

- **Claude API** — multi-turn conversation, tool use, multilingual
- **Twilio Voice** — inbound call, speech-to-text, text-to-speech, call transfer
- **Twilio SMS** — clinic details to user's phone
- **Supabase** — HRSA clinic data, ranking queries
- **FastAPI** — backend webhook handler
- **Next.js** — real-time dashboard

## Setup

### 1. Clone and install

```bash
git clone <repo>
cd clearpath

# Backend
cd backend
pip install -r requirements.txt

# Dashboard
cd ../dashboard
npm install
```

### 2. Environment variables

```bash
cp .env.example .env
```

Fill in:

```
ANTHROPIC_API_KEY=
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_PHONE_NUMBER=
SUPABASE_URL=
SUPABASE_ANON_KEY=
```

### 3. Seed clinic data

```bash
cd data
python seed_clinics.py
```

Loads 20–30 enriched LA clinics from HRSA dataset into Supabase.

### 4. Run backend

```bash
cd backend
uvicorn main:app --reload --port 8000
```

Expose via ngrok for Twilio webhooks:

```bash
ngrok http 8000
```

Set Twilio webhook URL to: `https://<ngrok-url>/voice`

### 5. Run dashboard

```bash
cd dashboard
npm run dev
```

Open `http://localhost:3000` — shows real-time conversation and analysis during calls.

## Project Structure

```
clearpath/
├── backend/
│   ├── main.py              # FastAPI app, Twilio webhooks
│   ├── claude_pipeline.py   # Claude multi-turn conversation
│   ├── clinic_search.py     # Supabase query + ranking
│   ├── twilio_handler.py    # TwiML response builder
│   └── sms.py               # SMS sender
├── dashboard/               # Next.js real-time display
│   └── pages/index.tsx
├── data/
│   └── seed_clinics.py      # HRSA data loader
└── .env.example
```

## Demo

Call the Twilio number and say:

> _"I have a bad tooth infection. I make about $1,800 a month and I don't have insurance. I'm in East LA."_

ClearPath will triage, find the best dental clinic near you, explain why it was chosen, and offer to connect the call or send details by text.

## Data

Clinic data sourced from [HRSA Health Center Service Delivery Sites](https://data.hrsa.gov) — official US government dataset of federally qualified health centers (FQHCs). All clinics are legally required to offer sliding-scale fees. Updated April 2026.

## Ethical Design

- Any life-threatening symptoms → "Call 911 immediately" — hardcoded, no exceptions
- Claude navigates, never diagnoses
- User always chooses the clinic — Claude recommends, human decides
- "You likely qualify" — never confirms eligibility, that's a clinic decision
- Works in any language — serves non-English speakers equally
