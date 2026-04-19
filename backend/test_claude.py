#!/usr/bin/env python3
"""
Quick test to verify Claude API integration after library upgrade.
"""
import os
from dotenv import load_dotenv
import anthropic

# Load environment variables
load_dotenv()

# Test Claude API connection
def test_claude_api():
    print("[TEST] Testing Claude API connection...")

    try:
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        print("[TEST] Client created successfully")

        # Simple test message
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=50,
            messages=[{"role": "user", "content": "Say hello in exactly 3 words"}]
        )

        print("[TEST] API call successful!")
        print(f"[TEST] Response: {response.content[0].text}")
        return True

    except Exception as e:
        print(f"[TEST] Error: {e}")
        return False

if __name__ == "__main__":
    success = test_claude_api()
    print(f"[TEST] Claude API test {'PASSED' if success else 'FAILED'}")