# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What We're Building

**ClearPath** — a voice-based AI navigator that helps uninsured Americans find free or low-cost clinics near them. Users call a phone number, describe their situation in plain language (any language), and Claude triages urgency, checks eligibility, finds the best-matched clinic, and either connects the call directly to the clinic or sends clinic details via SMS.

No app. No typing. Just call.

---

## Hackathon Context

- **Event:** SoCal Claude Hackathon — April 19, 2026, UCLA
- **Build window:** 10:00 AM – 4:00 PM (6 hours)
- **DevPost deadline:** 4:15 PM
- **Demo:** 3-min demo + 2-min Q&A
- **Track:** Health & Wellbeing
- **Team:** 2 people

---

## Full Conversation Flow

```
User calls Twilio number
        ↓
Twilio: "Hi, I'm ClearPath. Describe your situation and I'll find free care near you."
        ↓
User speaks (any language)
        ↓
Twilio transcribes speech → POST to /voice webhook (FastAPI)
        ↓
Backend sends transcript to Claude (multi-turn conversation begins)
        ↓
Claude asks follow-up questions if needed:
  "What city or ZIP are you in?"
  "And roughly what's your monthly income?"
        ↓
User answers each question (each answer → new Twilio Gather → new Claude turn)
        ↓
Claude has enough info → calls find_clinics tool
        ↓
Backend queries Supabase (ranked by distance, service match, eligibility)
        ↓
Claude generates explanation in user's language:
  "My top match is Clinica Romero, 1.8 miles away.
   They specialize in dental, accept uninsured patients,
   sliding-scale fees likely $0–20. I chose them because
   they're closest, open today, and have Spanish support.
   Would you like to go with Clinica Romero?"
        ↓
Twilio speaks response back to user
        ↓
User says "yes" or "no, show next option"
        ↓
If YES:
  Claude: "Would you like me to connect you now or send details by text?"
  User: "connect me" → Twilio <Dial> transfers call to clinic
  User: "text me"   → Twilio sends SMS with clinic details
        ↓
If NO:
  Claude presents next ranked clinic with explanation
  Loop repeats
```

---

## Tech Stack

| Layer | Tool | Purpose |
|---|---|---|
| Phone calls | Twilio Voice | Inbound call, STT, TTS, call transfer |
| SMS | Twilio SMS | Send clinic details to user's phone |
| AI pipeline | Claude API (claude-sonnet-4-6) | Multi-turn conversation, tool use, multilingual |
| Database | Supabase (PostgreSQL) | HRSA clinic data, ranking queries |
| Backend | FastAPI (Python) | Webhook handler, Claude orchestration |
| Dashboard | Next.js | Real-time conversation + analysis display for demo |

---

## Project Structure

```
clearpath/
├── backend/
│   ├── main.py              # FastAPI app, Twilio webhooks
│   ├── claude_pipeline.py   # Claude multi-turn conversation logic
│   ├── clinic_search.py     # Supabase query + ranking algorithm
│   ├── twilio_handler.py    # TwiML response builder
│   └── sms.py               # Twilio SMS sender
├── dashboard/               # Next.js real-time display
│   ├── pages/index.tsx      # Dashboard UI
│   └── components/
│       ├── ConversationLog.tsx
│       └── ClinicResults.tsx
├── data/
│   └── seed_clinics.py      # Script to load HRSA data into Supabase
└── .env
```

---

## Environment Variables

```
ANTHROPIC_API_KEY=
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_PHONE_NUMBER=
SUPABASE_URL=
SUPABASE_ANON_KEY=
```

---

## Supabase Schema

```sql
CREATE TABLE clinics (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  name text NOT NULL,
  address text,
  city text,
  zip text,
  phone text,
  website text,
  lat float,
  lng float,
  services text[],          -- ['dental', 'primary_care', 'mental_health']
  languages text[],         -- ['english', 'spanish', 'korean']
  sliding_fee boolean DEFAULT true,
  accepts_uninsured boolean DEFAULT true,
  hours text,
  score_boost int DEFAULT 0
);
```

Seed from HRSA data: filter `Site State Abbreviation = CA`, `Site City = LOS ANGELES`, manually enrich 20–30 rows with `services` and `languages`.

---

## Claude Pipeline

### Tool Use Schema

```python
tools = [{
    "name": "find_clinics",
    "description": "Find and rank free/low-cost clinics based on user's situation",
    "input_schema": {
        "type": "object",
        "properties": {
            "urgency": {
                "type": "string",
                "enum": ["911", "urgent", "routine"],
                "description": "Medical urgency level"
            },
            "service_type": {
                "type": "string",
                "enum": ["dental", "primary_care", "mental_health", "vision", "general"],
                "description": "Type of medical service needed"
            },
            "zip": {"type": "string", "description": "User's ZIP code"},
            "language": {"type": "string", "description": "User's language"},
            "fqhc_eligible": {"type": "boolean"},
            "medicaid_eligible": {"type": "boolean"}
        },
        "required": ["urgency", "service_type", "zip"]
    }
}]
```

### Structured Response Format

Claude returns this JSON after finding clinics:

```json
{
  "response_text": "My top match is Clinica Romero, 1.8 miles away...",
  "action": "present_clinic",
  "clinic": {
    "name": "Clinica Romero",
    "address": "123 E César Chávez Ave, Los Angeles",
    "phone": "+13232345678",
    "reason": "Closest dental clinic, open today, sliding-scale confirmed"
  },
  "next_prompt": "Would you like to go with this clinic?"
}
```

`action` values: `ask_followup`, `present_clinic`, `transfer_call`, `send_sms`, `call_911`

### System Prompt

```
You are ClearPath, a compassionate AI that helps uninsured people find free or low-cost medical care.

CRITICAL SAFETY RULE: If the user describes ANY life-threatening symptoms (chest pain, difficulty breathing, severe bleeding, stroke symptoms, loss of consciousness), immediately respond: "This sounds like an emergency. Please call 911 right now." Do not proceed to find clinics.

Your job:
1. Gather: condition, ZIP code, monthly income, language
2. Determine urgency (911 / urgent / routine)
3. Check eligibility: FQHC (income ≤ 200% FPL), Medicaid (income ≤ 138% FPL)
4. Call find_clinics tool when you have enough information
5. Present top clinic with clear explanation of WHY it was chosen
6. Ask if user wants this clinic or the next option
7. Ask if they want call transfer or SMS

LANGUAGE: Always detect the user's language and respond entirely in that language.
TONE: Warm, clear, never medical jargon. You are a helpful navigator, not a doctor.
NEVER diagnose. NEVER guarantee eligibility. Say "you likely qualify" not "you qualify."
Federal Poverty Level reference (single adult): 100% = $15,060/yr, 138% = $20,783/yr, 200% = $30,120/yr
```

---

## Clinic Ranking Algorithm

Two-step process: scoring pre-filters candidates, then Claude reasons about the best fit and generates the spoken explanation.

### Step 1 — Scoring pre-filter (deterministic, fast)

```python
def score_clinic(clinic, user_zip, service_type, language):
    score = 0
    score += 40 if service_type in clinic['services'] else 0
    score += 25 * max(0, (10 - distance_miles(user_zip, clinic)) / 10)
    score += 20 if clinic['sliding_fee'] else 0
    score += 10 if language in clinic['languages'] else 0
    score += clinic.get('score_boost', 0)
    return score

# Returns top 5 candidates to pass to Claude
candidates = sorted(clinics, key=lambda c: score_clinic(c, zip, service_type, language), reverse=True)[:5]
```

### Step 2 — Claude reasoning (intelligent, explainable)

Pass the top 5 candidates back to Claude as the `find_clinics` tool result:

```python
tool_result = {
    "candidates": [
        {
            "name": "Clinica Romero",
            "address": "123 E César Chávez Ave",
            "phone": "+13232345678",
            "distance_miles": 1.8,
            "services": ["dental", "primary_care"],
            "languages": ["english", "spanish"],
            "sliding_fee": True,
            "hours": "Mon-Fri 8am-5pm",
            "score": 95
        },
        # ... 4 more
    ]
}
```

Claude then:
1. Reasons about which clinic is truly best for this specific user
2. Generates a spoken explanation of WHY it chose that clinic
3. Returns structured response with `response_text`, `clinic`, `action`

This is better than pure semantic search because Claude can explain its reasoning out loud to the caller — which is the core demo moment. No separate embedding model needed.

---

## Twilio Call Flow

### Inbound call webhook (`POST /voice`)
1. Respond with TwiML `<Say>` greeting
2. `<Gather input="speech">` to capture user speech
3. On speech received → send to Claude → get response
4. `<Say>` Claude's response back to user
5. `<Gather>` again for next user turn
6. Repeat until `action = transfer_call` or `action = send_sms`

### Call transfer
```python
response = VoiceResponse()
response.say("Connecting you now.")
response.dial(clinic_phone_number)
```

### SMS after call
```python
client.messages.create(
    body=f"ClearPath: {clinic_name}\n{address}\n{phone}\nBring: photo ID + proof of income\nEst. cost: $0-20",
    from_=TWILIO_PHONE_NUMBER,
    to=caller_number
)
```

---

## Dashboard (Demo Display)

Simple Next.js page that polls `GET /call-state` every second and displays:

```
📞 Incoming call...

💬 CONVERSATION
─────────────────────────────────
🤖 Hi, I'm ClearPath...
👤 I have a tooth infection, no insurance
🤖 What city or ZIP are you in?
👤 East LA, 90022
🤖 And roughly what's your monthly income?
👤 About $1,800 driving Uber
─────────────────────────────────

🔍 CLAUDE ANALYSIS
   Urgency: non-emergency ✅
   Service: dental
   ZIP: 90022
   FQHC eligible: ✅
   Medicaid eligible: ✅
   Language: English

🏥 CLINIC RANKING
   1. Clinica Romero ............ 95
   2. Northeast Valley Health ... 87
   3. APLA Health ............... 82

💬 Presenting top clinic...
📞 Transferring call... ✅
📱 SMS sent ✅
```

Store call state in a simple in-memory dict on the backend. Dashboard polls it.

---

## Build Order (6 hours, 2 people)

**Person A — Twilio + Backend**
**Person B — Claude + Data + Dashboard**

```
Hour 1:
  A: FastAPI skeleton + Twilio inbound call webhook + basic <Say>/<Gather> loop
  B: Claude pipeline with hardcoded test input, confirm tool use works

Hour 2:
  A: Wire Twilio STT → POST to Claude endpoint
  B: Supabase setup + seed 20 LA clinics + ranking query

Hour 3:
  A+B: Connect end-to-end — call → Claude → Supabase → TTS response

Hour 4:
  A: Call transfer (<Dial>) + SMS
  B: Multi-turn conversation state + full system prompt

Hour 5:
  B: Dashboard polling + display
  A+B: Full demo run-through, fix bugs

Hour 6:
  Fix remaining bugs, rehearse demo twice, prep pitch
```

---

## Demo Script (3 minutes)

**Setup:** Laptop shows dashboard. Phone on table face-up. Twilio number ready to call.

**[0:00]** Call the Twilio number on the demo phone.
**[0:05]** ClearPath answers. Speak: *"I have a bad tooth infection. I've had it for 3 days and it's getting worse."*
**[0:20]** Claude asks for ZIP. Say: *"East LA, 90022"*
**[0:30]** Claude asks for income. Say: *"About $1,800 a month, I drive for Uber"*
**[0:45]** Claude presents Clinica Romero with explanation. Judges see dashboard update in real time.
**[1:00]** Say: *"Yes"*
**[1:05]** Claude asks: call or text? Say: *"Connect me"*
**[1:10]** Twilio transfers call to teammate's phone. Teammate answers: *"Clinica Romero, how can I help?"*
**[1:20]** Hang up. Demo complete.

**Spoken pitch alongside demo:**
- Typing message: "Maria describes her situation the way she'd call a friend — no app, no typing"
- Claude responds: "Claude triages urgency, checks eligibility, and finds the best match"
- Dashboard updates: "Judges see the full reasoning pipeline in real time"
- Call transfers: "We don't just find the clinic — we connect the call"

**Closing line:**
> "Maria went from 'I can't afford a doctor' to connected with a clinic in under 90 seconds. That gap exists for 27 million Americans. We closed it."

---

## Q&A Prep

| Question | Answer |
|---|---|
| Does this work outside LA? | Demo uses LA — production ingests all 14,000+ HRSA sites nationwide |
| How do you know fees are accurate? | Sliding-scale is federal law for all FQHCs — we don't fabricate prices |
| Different from Google? | Google returns a list. We triage, confirm eligibility, explain why, and connect the call |
| What if Claude gets eligibility wrong? | We say "you likely qualify" — never confirm. That's a human decision at the clinic |
| What about emergencies? | Any life-threatening symptoms → "Call 911 immediately." Hardcoded, no exceptions |
| Scale? | Replace manual enrichment with automated HRSA scraping. Same pipeline |
| Business model? | Grant-funded or nonprofit — same model as 211 and similar navigation tools |

---

## Judging Rubric Alignment

| Criterion | Points | Our angle |
|---|---|---|
| Impact | 30 | 27M uninsured + ACA crisis Jan 2026, specific person (Maria), real HRSA data |
| Technical | 30 | Claude tool use + multi-turn + multilingual + Supabase ranking + call transfer |
| Ethical | 20 | 911 hardcoded, Claude navigates not diagnoses, user always chooses, "likely qualifies" not "qualifies" |
| Presentation | 20 | Live call demo, real-time dashboard, call transfer moment |
