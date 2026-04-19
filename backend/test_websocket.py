"""
Integration test for WebSocket conversation flow and dashboard updates.
Tests the real-time dashboard WebSocket functionality.

Run:
    cd backend
    python test_websocket.py
"""

import asyncio
import json
import websockets
import requests
import time

async def simulate_conversation_websocket():
    """Simulate a ConversationRelay WebSocket conversation."""
    uri = "ws://localhost:8000/ws"

    print(f"[TEST] Connecting to conversation WebSocket: {uri}")

    async with websockets.connect(uri) as websocket:
        print("[TEST] Connected to conversation WebSocket")

        # Simulate initial call connection
        call_sid = f"test_call_{int(time.time())}"
        init_message = {
            "type": "setup",
            "call_sid": call_sid
        }
        await websocket.send(json.dumps(init_message))
        print(f"[TEST] Sent call setup with SID: {call_sid}")

        # Wait a moment
        await asyncio.sleep(1)

        # Simulate user speech
        user_message = {
            "type": "prompt",
            "voicePrompt": "I have a bad tooth infection and no insurance. I'm in East LA."
        }
        await websocket.send(json.dumps(user_message))
        print("[TEST] Sent user speech about tooth infection")

        # Listen for Claude's response
        response = await websocket.recv()
        response_data = json.loads(response)
        print(f"[TEST] Received Claude response: {response_data.get('token', 'No token')[:50]}...")

        return call_sid

async def test_dashboard_updates():
    """Test dashboard WebSocket updates during conversation."""
    uri = "ws://localhost:8000/dashboard"

    print(f"[TEST] Connecting to dashboard WebSocket: {uri}")

    async with websockets.connect(uri) as websocket:
        print("[TEST] Connected to dashboard WebSocket")

        # Send heartbeat
        await websocket.send(json.dumps({"type": "ping"}))

        # Listen for updates
        updates_received = 0
        start_time = time.time()

        while updates_received < 3 and (time.time() - start_time) < 30:  # Wait max 30 seconds
            try:
                message = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                data = json.loads(message)
                updates_received += 1

                print(f"[TEST] Dashboard update #{updates_received}: {data.get('type', 'unknown')}")

                if data.get("type") == "conversation_update":
                    print(f"       📞 Call: {data.get('call_sid', 'Unknown')[:12]}...")
                    print(f"       💬 Messages: {data.get('total_messages', 0)}")
                    print(f"       🏥 Service: {data.get('session_metadata', {}).get('service_needed', 'Unknown')}")
                    print(f"       💰 Eligibility: {data.get('session_metadata', {}).get('eligibility_status', 'Unknown')}")
                elif data.get("type") == "call_connected":
                    print(f"       📞 Call connected: {data.get('call_sid', 'Unknown')[:12]}...")

            except asyncio.TimeoutError:
                print("[TEST] Timeout waiting for dashboard updates")
                break

        print(f"[TEST] Received {updates_received} dashboard updates")
        return updates_received > 0

async def run_integration_test():
    """Run full integration test."""
    print("=== Call2Well WebSocket Integration Test ===\n")

    # Test 1: Dashboard connection
    print("📋 Step 1: Testing dashboard WebSocket connection...")
    try:
        # Quick connection test
        async with websockets.connect("ws://localhost:8000/dashboard") as ws:
            await ws.send(json.dumps({"type": "ping"}))
            response = await asyncio.wait_for(ws.recv(), timeout=3.0)
            response_data = json.loads(response)
            if response_data.get("type") == "pong":
                print("   ✅ Dashboard WebSocket connection working")
            else:
                print("   ❌ Dashboard WebSocket ping/pong failed")
                return False
    except Exception as e:
        print(f"   ❌ Dashboard WebSocket connection failed: {e}")
        return False

    # Test 2: Conversation WebSocket with dashboard monitoring
    print("\n💬 Step 2: Testing conversation WebSocket with dashboard monitoring...")

    # Start dashboard monitoring in background
    dashboard_task = asyncio.create_task(test_dashboard_updates())

    # Give dashboard time to connect
    await asyncio.sleep(1)

    # Simulate conversation
    try:
        await simulate_conversation_websocket()
        print("   ✅ Conversation WebSocket working")
    except Exception as e:
        print(f"   ❌ Conversation WebSocket failed: {e}")
        dashboard_task.cancel()
        return False

    # Wait for dashboard updates
    dashboard_success = await dashboard_task

    if dashboard_success:
        print("   ✅ Dashboard received real-time updates")
    else:
        print("   ❌ Dashboard did not receive expected updates")
        return False

    print("\n🎉 All tests passed! Real-time dashboard WebSocket system is working.")
    return True

if __name__ == "__main__":
    success = asyncio.run(run_integration_test())
    exit(0 if success else 1)