"""
Call2Well Claude pipeline.
Manages multi-turn conversation, tool use, and structured responses.

Usage:
    session = Call2WellSession()
    response = session.process("I have a tooth infection, no insurance, East LA")
    print(response["response_text"])
"""

import json
import os
import anthropic
from dotenv import load_dotenv
from clinic_search import find_clinics

# Load environment variables from .env file
load_dotenv()

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

SYSTEM_PROMPT = """You are Call2Well, a compassionate AI that helps uninsured people find free or low-cost medical care in Los Angeles.

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
7. If they want this clinic, ask: "Would you like me to connect you directly or send the details to your phone?"

TRANSFER CONFIRMATION: When user says any of these phrases, use "transfer_call" action:
- "connect me", "transfer me", "call them", "dial them"
- "yes connect", "connect now", "put me through"
- "direct me", "transfer the call"

SMS REQUEST: When user asks for text/SMS, use "send_sms" action:
- "send text", "text me", "send details", "SMS me"

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

RESPONSE FORMAT - CRITICAL: You MUST respond with ONLY valid JSON. No extra text, no explanations, no stage directions. Only the JSON structure below:

{
  "response_text": "The exact words to speak to the user - natural, conversational language only",
  "action": "action_type",
  "clinic": {
    "name": "clinic name",
    "address": "full address",
    "phone": "phone number",
    "reason": "Brief reason why this clinic was chosen"
  },
  "next_prompt": "Follow-up question if needed"
}

action values:
- "ask_followup" → need more info, response_text contains the question
- "present_clinic" → found a match, include clinic object
- "transfer_call" → user confirmed, ready to transfer
- "send_sms" → user wants text instead
- "call_911" → emergency detected

IMPORTANT: The "response_text" field should contain ONLY natural conversational language that will be read aloud to the user. No JSON, no technical details, no stage directions.
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


class Call2WellSession:
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
        print(f"[CLAUDE DEBUG] Processing user message: '{user_message}'")

        # Add user message to history
        self.messages.append({
            "role": "user",
            "content": user_message
        })
        print(f"[CLAUDE DEBUG] Message history length: {len(self.messages)}")

        # Call Claude
        print(f"[CLAUDE DEBUG] Calling Claude API...")
        try:
            response = client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=self.messages
            )
            print(f"[CLAUDE DEBUG] Claude API response received. Stop reason: {response.stop_reason}")
        except Exception as e:
            print(f"[CLAUDE DEBUG] Claude API error: {e}")
            return {
                "response_text": "I'm having trouble processing your request right now. Please try again.",
                "action": "ask_followup",
                "clinic": None,
                "next_prompt": None
            }

        # Handle tool use
        if response.stop_reason == "tool_use":
            print(f"[CLAUDE DEBUG] Claude wants to use tools")
            return self._handle_tool_use(response)

        # Handle regular text response
        print(f"[CLAUDE DEBUG] Claude returned text response")
        return self._handle_text_response(response)

    def _handle_tool_use(self, response) -> dict:
        """Claude called find_clinics — execute it and continue."""
        print(f"[CLAUDE DEBUG] Handling tool use...")

        # Add assistant's tool call to history
        self.messages.append({
            "role": "assistant",
            "content": response.content
        })

        # Find the tool use block
        tool_use_block = next(b for b in response.content if b.type == "tool_use")
        tool_input = tool_use_block.input
        print(f"[CLAUDE DEBUG] Tool input: {tool_input}")

        # Store session state
        if tool_input.get("zip"):
            self.call_state["user_zip"] = tool_input["zip"]
        if tool_input.get("monthly_income"):
            self.call_state["monthly_income"] = tool_input["monthly_income"]
        if tool_input.get("language"):
            self.call_state["language"] = tool_input["language"]

        # Execute clinic search
        print(f"[CLAUDE DEBUG] Calling find_clinics with: {tool_input}")
        try:
            candidates = find_clinics(
                zip_code=tool_input.get("zip", "90022"),
                service_type=tool_input.get("service_type", "primary_care"),
                language=tool_input.get("language", "english")
            )
            print(f"[CLAUDE DEBUG] Found {len(candidates)} candidates")
        except Exception as e:
            print(f"[CLAUDE DEBUG] find_clinics error: {e}")
            candidates = []

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
            model="claude-3-haiku-20240307",
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

        print(f"[CLAUDE DEBUG] Raw Claude response: {repr(text)}")

        # Try to parse as JSON (Claude should return JSON when presenting clinics)
        result = self._extract_json_from_text(text)

        if result:
            # Store chosen clinic for any action that includes clinic info
            if result.get("clinic"):
                self.call_state["chosen_clinic"] = result["clinic"]
                print(f"[CLAUDE DEBUG] Stored clinic: {result['clinic']['name']}")

            # For transfer_call, ensure we have the clinic info from state
            if result.get("action") == "transfer_call":
                if not result.get("clinic") and self.call_state.get("chosen_clinic"):
                    result["clinic"] = self.call_state["chosen_clinic"]
                    print(f"[CLAUDE DEBUG] Added clinic from state for transfer: {result['clinic']['name']}")

            # Clean the response_text to ensure only natural language
            if "response_text" in result:
                result["response_text"] = self._clean_response_text(result["response_text"])

            print(f"[CLAUDE DEBUG] Extracted JSON: {result}")
            return result
        else:
            # Claude returned plain text — wrap it and clean it
            clean_text = self._clean_response_text(text)
            print(f"[CLAUDE DEBUG] Fallback to plain text: {repr(clean_text)}")
            return {
                "response_text": clean_text,
                "action": "ask_followup",
                "clinic": None,
                "next_prompt": None
            }

    def _extract_json_from_text(self, text: str) -> dict:
        """Extract JSON from text that might contain extra content."""
        import re

        # Try to find JSON within the text using regex
        json_pattern = r'\{[\s\S]*?\}'
        matches = re.findall(json_pattern, text)

        for match in matches:
            try:
                result = json.loads(match)
                # Validate it has the expected structure
                if "response_text" in result and "action" in result:
                    return result
            except json.JSONDecodeError:
                continue

        # Try parsing the whole text as JSON
        try:
            # Handle markdown code blocks
            clean = text.strip()
            if "```" in clean:
                clean = clean.split("```")[1]
                if clean.startswith("json"):
                    clean = clean[4:]
            result = json.loads(clean.strip())
            if "response_text" in result and "action" in result:
                return result
        except (json.JSONDecodeError, IndexError):
            pass

        return None

    def _clean_response_text(self, text: str) -> str:
        """Clean response text to remove JSON artifacts and stage directions."""
        import re

        # Remove JSON blocks
        text = re.sub(r'\{[\s\S]*?\}', '', text)

        # Remove markdown code blocks
        text = re.sub(r'```[\s\S]*?```', '', text)

        # Remove stage directions like *transfers the call*
        text = re.sub(r'\*[^*]*\*', '', text)

        # Remove extra whitespace and newlines
        text = ' '.join(text.split())

        return text.strip()
