"""
Test the WebSocket ConversationRelay integration without Twilio.
Simulates the conversation flow locally.

Run:
    cd backend
    python test_websocket.py
"""

import asyncio
import json
from claude_pipeline import ClearPathSession


async def simulate_websocket_conversation():
    """Simulate the WebSocket conversation flow."""
    print("=" * 60)
    print("ClearPath WebSocket Simulation Test")
    print("=" * 60)

    # Initialize Claude session (same as in main.py)
    claude_session = ClearPathSession()

    # Simulate ConversationRelay messages
    test_messages = [
        {
            "type": "user_speech",
            "text": "Hi, I have a really bad toothache — I think it might be infected — and I don't have insurance. I'm near Cesar Chavez in East LA and I can't really afford to go to the ER."
        },
        {
            "type": "user_speech",
            "text": "90033"
        },
        {
            "type": "user_speech",
            "text": "About $1,800 driving Uber"
        },
        {
            "type": "user_speech",
            "text": "Yes, that sounds perfect"
        },
        {
            "type": "user_speech",
            "text": "Connect me please"
        }
    ]

    for i, message in enumerate(test_messages):
        print(f"\n--- Turn {i+1} ---")
        print(f"👤 User: {message['text']}")

        # Process through Claude pipeline (same logic as main.py WebSocket handler)
        response = claude_session.process(message["text"])

        print(f"🤖 ClearPath: {response.get('response_text', '')}")
        print(f"   Action: {response.get('action', 'unknown')}")

        if response.get("clinic"):
            clinic = response["clinic"]
            print(f"   Clinic: {clinic.get('name')} | {clinic.get('phone')}")
            print(f"   Distance: {clinic.get('distance_miles', 'Unknown')} miles")
            print(f"   Reason: {clinic.get('reason')}")

        # Simulate WebSocket response
        websocket_response = {
            "type": "assistant_speech",
            "text": response.get("response_text")
        }

        action = response.get("action")
        if action == "transfer_call":
            clinic = response.get("clinic")
            if clinic and clinic.get("phone"):
                websocket_response["transfer_to"] = clinic["phone"]
                print(f"   📞 Would transfer to: {clinic['phone']}")
                break
        elif action == "send_sms":
            print(f"   📱 Would send SMS with clinic details")
            websocket_response["end_conversation"] = True
            break
        elif action == "call_911":
            print(f"   🚨 Emergency detected - would end call")
            websocket_response["end_conversation"] = True
            break

        print(f"   WebSocket Response: {json.dumps(websocket_response, indent=2)}")

    print("\n" + "=" * 60)
    print("Session State:")
    print(f"  ZIP: {claude_session.call_state.get('user_zip')}")
    print(f"  Income: ${claude_session.call_state.get('monthly_income')}/month")
    print(f"  Language: {claude_session.call_state.get('language')}")
    print(f"  Candidates: {len(claude_session.call_state.get('candidates', []))}")
    if claude_session.call_state.get("chosen_clinic"):
        chosen = claude_session.call_state["chosen_clinic"]
        print(f"  Chosen: {chosen['name']}")
        print(f"  Phone: {chosen.get('phone', 'N/A')}")

    print("\n✅ WebSocket simulation complete!")


async def test_emergency_detection():
    """Test emergency detection."""
    print("\n" + "=" * 60)
    print("Emergency Detection Test")
    print("=" * 60)

    session = ClearPathSession()
    response = session.process("I'm having chest pain and can't breathe")

    print(f"👤 User: I'm having chest pain and can't breathe")
    print(f"🤖 ClearPath: {response.get('response_text', '')}")
    print(f"   Action: {response.get('action')}")

    if response.get("action") == "call_911" or "911" in response.get("response_text", ""):
        print("✅ Emergency correctly detected")
    else:
        print("❌ Emergency NOT detected!")


if __name__ == "__main__":
    asyncio.run(test_emergency_detection())
    asyncio.run(simulate_websocket_conversation())