"""
ClearPath Claude pipeline.
Manages multi-turn conversation, tool use, and structured responses.

Usage:
    session = ClearPathSession()
    response = session.process("I have a tooth infection, no insurance, East LA")
    print(response["response_text"])
"""

import json
import os
import anthropic
from clinic_search import find_clinics

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

SYSTEM_PROMPT = """You are ClearPath, a compassionate AI that helps uninsured people find free or low-cost medical care in Los Angeles.

CRITICAL SAFETY RULE: If the user describes ANY life-threatening symptoms (chest pain, difficulty breathing, severe bleeding, stroke symptoms, loss of consciousness, suicidal thoughts), immediately say: "This sounds like an emergency. Please call 911 right now." Do not proceed to find clinics.

Your job:
1. Gather information through natural conversation:
   - What is their condition or symptom?
   - What city or ZIP code are they in?
   - Roughly what is their monthly income? (to estimate cost)
2. Determine urgency: 911 / urgent / routine
3. Check eligibility:
   - FQHC sliding-scale: income ≤ 200% FPL ($2,510/month for single adult) → qualifies
   - Medicaid (Medi-Cal in CA): income ≤ 138% FPL ($1,732/month) → likely qualifies
4. When you have condition + ZIP + income → call the find_clinics tool
5. Present the top clinic with a clear explanation of WHY it was chosen
6. Ask if the user wants this clinic or to see the next option
7. If they want this clinic, ask: connect the call now, or send details by text?

LANGUAGE: Detect the user's language from their message. Respond entirely in that language for the whole conversation.
TONE: Warm, clear, never medical jargon. You are a navigator, not a doctor.
NEVER diagnose. NEVER guarantee eligibility. Say "you likely qualify" not "you qualify."
NEVER make up clinic names or phone numbers. Only use what the find_clinics tool returns.

Federal Poverty Level (single adult, 2026):
- 100% FPL = $1,255/month
- 138% FPL = $1,732/month (Medi-Cal threshold)
- 200% FPL = $2,510/month (FQHC sliding scale threshold)

Cost estimation (use this when explaining to the user):
- Income < $1,255/month → $0, fully covered
- Income $1,255–$1,732/month → $0–$10
- Income $1,732–$2,510/month → $10–$40
- Income > $2,510/month → $40+ (still reduced)

After find_clinics returns results, respond with this exact JSON structure:
{
  "response_text": "The spoken response to read to the user",
  "action": "present_clinic",
  "clinic": {
    "name": "...",
    "address": "...",
    "phone": "...",
    "reason": "Why this clinic was chosen"
  },
  "next_prompt": "Would you like to go with this clinic?"
}

action values:
- "ask_followup" → need more info, response_text is the question
- "present_clinic" → found a match, include clinic object
- "transfer_call" → user confirmed, ready to transfer
- "send_sms" → user wants text instead
- "call_911" → emergency detected
"""

TOOLS = [
    {
        "name": "find_clinics",
        "description": "Find and rank free/low-cost clinics based on user's situation. Call this when you have the user's condition, ZIP code, and income.",
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
                "zip": {
                    "type": "string",
                    "description": "User's ZIP code (5 digits)"
                },
                "language": {
                    "type": "string",
                    "description": "User's language (e.g. english, spanish)"
                },
                "monthly_income": {
                    "type": "number",
                    "description": "User's monthly income in dollars"
                }
            },
            "required": ["urgency", "service_type", "zip"]
        }
    }
]


def estimate_cost(monthly_income: float) -> str:
    annual = monthly_income * 12
    if annual < 15060:
        return "$0 — fully covered"
    elif annual < 20783:
        return "$0–$10"
    elif annual < 30120:
        return "$10–$40"
    else:
        return "$40+ (still reduced)"


class ClearPathSession:
    """Manages a single call session with multi-turn conversation."""

    def __init__(self):
        self.messages = []
        self.call_state = {
            "status": "gathering",  # gathering → presenting → confirmed
            "candidates": [],       # top 5 clinics from find_clinics
            "current_index": 0,     # which clinic we're presenting
            "chosen_clinic": None,
            "user_zip": None,
            "monthly_income": None,
            "language": "english",
        }

    def process(self, user_message: str) -> dict:
        """
        Process one turn of conversation.
        Returns dict with response_text, action, and optionally clinic.
        """
        # Add user message to history
        self.messages.append({
            "role": "user",
            "content": user_message
        })

        # Call Claude
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=self.messages
        )

        # Handle tool use
        if response.stop_reason == "tool_use":
            return self._handle_tool_use(response)

        # Handle regular text response
        return self._handle_text_response(response)

    def _handle_tool_use(self, response) -> dict:
        """Claude called find_clinics — execute it and continue."""
        # Add assistant's tool call to history
        self.messages.append({
            "role": "assistant",
            "content": response.content
        })

        # Find the tool use block
        tool_use_block = next(b for b in response.content if b.type == "tool_use")
        tool_input = tool_use_block.input

        # Store session state
        if tool_input.get("zip"):
            self.call_state["user_zip"] = tool_input["zip"]
        if tool_input.get("monthly_income"):
            self.call_state["monthly_income"] = tool_input["monthly_income"]
        if tool_input.get("language"):
            self.call_state["language"] = tool_input["language"]

        # Execute clinic search
        print(f"[ClearPath] Searching clinics: {tool_input}")
        candidates = find_clinics(
            zip_code=tool_input.get("zip", "90022"),
            service_type=tool_input.get("service_type", "primary_care"),
            language=tool_input.get("language", "english")
        )

        # Add cost estimate to each candidate
        monthly_income = tool_input.get("monthly_income", 0)
        if monthly_income:
            cost_estimate = estimate_cost(monthly_income)
            for c in candidates:
                c["cost_estimate"] = cost_estimate

        self.call_state["candidates"] = candidates

        # Add tool result to history
        self.messages.append({
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": tool_use_block.id,
                "content": json.dumps({"candidates": candidates})
            }]
        })

        # Get Claude's response after seeing the results
        follow_up = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=self.messages
        )

        return self._handle_text_response(follow_up)

    def _handle_text_response(self, response) -> dict:
        """Parse Claude's text response into structured output."""
        text = response.content[0].text if response.content else ""

        # Add to history
        self.messages.append({
            "role": "assistant",
            "content": text
        })

        # Try to parse as JSON (Claude should return JSON when presenting clinics)
        try:
            # Handle markdown code blocks
            clean = text.strip()
            if "```" in clean:
                clean = clean.split("```")[1]
                if clean.startswith("json"):
                    clean = clean[4:]
            result = json.loads(clean.strip())
            # Store chosen clinic if presenting
            if result.get("action") == "present_clinic" and result.get("clinic"):
                self.call_state["chosen_clinic"] = result["clinic"]
            return result
        except (json.JSONDecodeError, IndexError):
            # Claude returned plain text — wrap it
            return {
                "response_text": text,
                "action": "ask_followup",
                "clinic": None,
                "next_prompt": None
            }
