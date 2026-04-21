#!/usr/bin/env python3
"""
Test script for dashboard WebSocket functionality.
Connects to the dashboard endpoint and listens for real-time updates.
"""

import asyncio
import json
import websockets
import sys

async def test_dashboard_connection():
    """Connect to dashboard WebSocket and listen for updates."""
    uri = "ws://localhost:8000/dashboard"

    try:
        print(f"[TEST] Connecting to dashboard WebSocket: {uri}")

        async with websockets.connect(uri) as websocket:
            print("[TEST] Connected successfully!")
            print("[TEST] Listening for dashboard updates...")

            # Send a ping to test bidirectional communication
            await websocket.send(json.dumps({"type": "ping"}))
            print("[TEST] Sent ping message")

            # Listen for incoming messages
            try:
                while True:
                    message = await websocket.recv()
                    try:
                        data = json.loads(message)
                        print(f"[TEST] Received update: {data.get('type', 'unknown')}")

                        # Pretty print the message based on type
                        if data.get("type") == "pong":
                            print("       ✓ Ping/pong working")
                        elif data.get("type") == "call_connected":
                            print(f"       📞 Call connected: {data.get('call_sid', 'Unknown')}")
                            print(f"       📱 From: {data.get('caller_number', 'Unknown')}")
                        elif data.get("type") == "conversation_update":
                            print(f"       💬 Conversation update for {data.get('call_sid', 'Unknown')}")
                            print(f"       📊 Messages: {data.get('total_messages', 0)}")
                            print(f"       🏥 Service: {data.get('session_metadata', {}).get('service_needed', 'Unknown')}")
                        elif data.get("type") == "call_status_change":
                            print(f"       🔄 Status change: {data.get('status', 'Unknown')}")
                            if data.get("clinic"):
                                print(f"       🏥 Clinic: {data['clinic'].get('name', 'Unknown')}")
                        else:
                            print(f"       📦 Full message: {json.dumps(data, indent=2)}")

                    except json.JSONDecodeError:
                        print(f"[TEST] Non-JSON message: {message}")

            except websockets.ConnectionClosed:
                print("[TEST] Connection closed by server")

    except ConnectionRefusedError:
        print("[TEST] ❌ Connection refused. Is the server running on localhost:8000?")
        sys.exit(1)
    except Exception as e:
        print(f"[TEST] ❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    print("=== ClearPath Dashboard WebSocket Test ===")
    print("This script will connect to the dashboard WebSocket and display real-time updates.")
    print("Make a test call to see updates in real-time!")
    print()

    try:
        asyncio.run(test_dashboard_connection())
    except KeyboardInterrupt:
        print("\n[TEST] Test stopped by user")