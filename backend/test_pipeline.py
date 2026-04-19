"""
Test the ClearPath Claude pipeline end-to-end.
Simulates Maria's call without Twilio.

Run:
    cd backend
    ANTHROPIC_API_KEY=... SUPABASE_URL=... SUPABASE_ANON_KEY=... python3 test_pipeline.py
"""

from claude_pipeline import ClearPathSession


def test_full_conversation():
    print("=" * 60)
    print("ClearPath Pipeline Test")
    print("=" * 60)

    session = ClearPathSession()

    # Simulate Maria's call
    conversation = [
        "I have a bad tooth infection. It's been 3 days and getting worse.",
        "East LA, 90022",
        "About $1,800 a month, I drive for Uber",
        "Yes, I want that clinic",
        "Connect me",
    ]

    for i, user_msg in enumerate(conversation):
        print(f"\n👤 User: {user_msg}")
        response = session.process(user_msg)
        print(f"🤖 ClearPath: {response.get('response_text', '')}")
        print(f"   Action: {response.get('action', 'unknown')}")
        if response.get("clinic"):
            clinic = response["clinic"]
            print(f"   Clinic: {clinic.get('name')} | {clinic.get('phone')}")
            print(f"   Reason: {clinic.get('reason')}")

        # Stop if we've reached transfer or SMS
        if response.get("action") in ["transfer_call", "send_sms", "call_911"]:
            print(f"\n✅ Call complete. Action: {response['action']}")
            break

    print("\n" + "=" * 60)
    print("Session state:")
    print(f"  ZIP: {session.call_state.get('user_zip')}")
    print(f"  Income: ${session.call_state.get('monthly_income')}/month")
    print(f"  Language: {session.call_state.get('language')}")
    print(f"  Candidates found: {len(session.call_state.get('candidates', []))}")
    if session.call_state.get("chosen_clinic"):
        print(f"  Chosen: {session.call_state['chosen_clinic']['name']}")


def test_emergency():
    print("\n" + "=" * 60)
    print("Emergency Detection Test")
    print("=" * 60)
    session = ClearPathSession()
    response = session.process("I'm having chest pain and can't breathe")
    print(f"🤖 ClearPath: {response.get('response_text', '')}")
    print(f"   Action: {response.get('action')}")
    assert response.get("action") == "call_911" or "911" in response.get("response_text", ""), \
        "❌ Emergency not detected!"
    print("✅ Emergency correctly detected")


def test_spanish():
    print("\n" + "=" * 60)
    print("Spanish Language Test")
    print("=" * 60)
    session = ClearPathSession()
    response = session.process("Tengo una infección dental y no tengo seguro médico")
    print(f"🤖 ClearPath: {response.get('response_text', '')}")
    print(f"   Action: {response.get('action')}")
    print("✅ Spanish test complete")


if __name__ == "__main__":
    test_emergency()
    test_spanish()
    test_full_conversation()
