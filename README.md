# Call2Well

> "We don't just find the clinic — we connect the call."

Call2Well is a voice-based AI navigator for the 27 million uninsured Americans who can't afford a doctor. Call a number, describe your situation in plain language, and Call2Well finds the best free clinic near you — then connects the call directly.

No app. No typing. No insurance jargon. Just call.

## How It Works

1. **Call** the Call2Well number
2. **Describe** your situation in any language
3. **Claude** triages urgency, checks eligibility, finds best-matched clinic
4. **Choose** to connect directly or receive clinic details by text

## Tech Stack

- **Claude API** — multi-turn conversation, tool use, multilingual (claude-3-haiku-20240307)
- **Twilio ConversationRelay** — real-time voice WebSocket integration
- **Supabase** — HRSA clinic data, ranking queries
- **FastAPI** — WebSocket server for ConversationRelay + real-time dashboard updates
- **Next.js + TypeScript** — live dashboard with hybrid WebSocket/polling updates
- **Real-time Features** — optimistic UI, typing indicators, auto-reconnect, session management

## Quick Start

### 1. Environment Setup

```bash
# Clone and set environment
cp .env.example .env
# Fill in API keys: ANTHROPIC_API_KEY, TWILIO_*, SUPABASE_*
```

### 2. Backend

```bash
cd backend
pip install -r requirements.txt

# Seed clinic data (if not already done)
cd ../data
python seed_clinics.py

# Start server
cd ../backend
uvicorn main:app --reload --port 8000
```

### 3. Expose with ngrok

```bash
ngrok http 8000
# Copy the https URL to .env as WEBSOCKET_URL
# Set Twilio webhook URL to: https://<ngrok-url>/voice
```

### 4. Dashboard

```bash
cd dashboard
npm install
npm run dev
# Open http://localhost:3000
```

### 5. Test the Pipeline

```bash
cd backend
python test_websocket.py  # Test without Twilio
python test_pipeline.py   # Test Claude pipeline directly
```

## Project Structure

```
clearpath/
├── backend/
│   ├── main.py              # FastAPI + ConversationRelay WebSocket
│   ├── claude_pipeline.py   # Claude conversation management
│   ├── clinic_search.py     # Supabase query + ranking
│   ├── test_websocket.py    # WebSocket simulation test
│   └── requirements.txt
├── dashboard/               # Next.js real-time display
│   ├── pages/index.tsx      # Dashboard UI
│   └── package.json
├── data/
│   ├── seed_clinics.py      # HRSA data loader
│   └── demo_scenario.json   # Perfect demo script
└── .env.example
```

## Demo Script

**Call the Twilio number and follow the demo scenario:**

> _"Hi, I have a really bad toothache — I think it might be infected — and I don't have insurance. I'm near Cesar Chavez in East LA and I can't really afford to go to the ER."_

**Expected flow:**
1. Claude asks for ZIP → "90033"
2. Claude asks for income → "About $1,800 driving Uber"
3. Claude presents AltaMed 1st Street (0.6 miles, dental specialist)
4. User accepts → "Yes, that sounds perfect"
5. Claude offers connection → "Connect me please"
6. Call transfers to AltaMed: 888-499-9303

**Dashboard shows:** Real-time conversation, Claude analysis, clinic ranking, and selected clinic details with coordinates ready for map integration.

## Architecture

```
Caller → Twilio Number → /voice webhook → <Connect><ConversationRelay>
    → WebSocket /ws → Claude Pipeline → Supabase Clinic Search
    → WebSocket Response → ConversationRelay → Caller
```

## Key Features

- **Real-time voice conversation** via Twilio ConversationRelay WebSocket
- **Multi-turn Claude integration** with tool use for clinic search
- **Sophisticated clinic ranking** with distance, service matching, language support
- **Emergency detection** — hardcoded 911 redirect for safety
- **Call transfer and SMS** — direct connection or clinic details by text
- **Multilingual support** — works in any language
- **Live dashboard** — real-time conversation display for demos
- **Coordinates included** — ready for map visualization

### Real-time Dashboard Features ✨
- **Hybrid update system** — WebSocket + polling fallback for bulletproof real-time updates
- **Optimistic UI updates** — instant visual feedback with loading states
- **Real-time typing indicators** — animated "thinking" displays when agent is processing
- **Auto-reconnect WebSocket** — seamless connection recovery
- **Session management** — clear all sessions with confirmation modal
- **Smooth animations** — fade-in effects and progress indicators for professional feel
- **Zero refresh required** — updates appear instantly without manual refresh

## Data

Clinic data from [HRSA Health Center Service Delivery Sites](https://data.hrsa.gov) — 306+ Los Angeles FQHCs with sliding-scale fees. All clinics legally required to serve uninsured patients.

## Ethical Design

- Any life-threatening symptoms → "Call 911 immediately" — hardcoded, no exceptions
- Claude navigates, never diagnoses
- User always chooses the clinic — Claude recommends, human decides
- "You likely qualify" — never confirms eligibility, that's a clinic decision
- Works in any language — serves non-English speakers equally

---

**Total build time:** ~3 hours
**Ready for:** Live demo, judge Q&A, map feature integration