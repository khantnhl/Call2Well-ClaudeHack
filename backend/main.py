"""
Call2Well FastAPI server with Twilio ConversationRelay WebSocket support.

Routes:
  GET /voice - Twilio webhook returning ConversationRelay TwiML
  WebSocket /ws - ConversationRelay WebSocket endpoint
  GET /call-state/{call_sid} - Dashboard polling endpoint

Run:
  uvicorn main:app --reload --port 8000
"""

import json
import os
import uuid
from typing import Dict
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()
import time

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from claude_pipeline import Call2WellSession
from twilio.twiml.voice_response import VoiceResponse
from twilio.rest import Client

app = FastAPI()

# CORS for dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Twilio client
twilio_client = Client(
    os.environ["TWILIO_ACCOUNT_SID"],
    os.environ["TWILIO_AUTH_TOKEN"]
)

# In-memory call state storage (use Redis in production)
call_sessions: Dict[str, dict] = {}

# Message deduplication storage
processed_messages: Dict[str, float] = {}
last_cleanup = time.time()

# Dashboard WebSocket connections
connected_dashboards = set()


@app.get("/voice")
@app.post("/voice")
async def voice_webhook(request: Request):
    """
    Twilio voice webhook - returns ConversationRelay TwiML.
    """
    print(f"[DEBUG] Voice webhook called with method: {request.method}")

    # Get call SID for session tracking (handle both GET and POST)
    if request.method == "POST":
        form_data = await request.form()
        call_sid = form_data.get("CallSid")
        caller_number = form_data.get("From")
    else:  # GET
        call_sid = request.query_params.get("CallSid")
        caller_number = request.query_params.get("From")

    print(f"[DEBUG] Call SID: {call_sid}, From: {caller_number}")

    # Check if this is a transfer callback
    if call_sid in call_sessions and call_sessions[call_sid].get("pending_transfer"):
        transfer_info = call_sessions[call_sid]["pending_transfer"]
        clinic_phone = transfer_info["clinic_phone"]
        clinic_name = transfer_info["clinic_name"]

        print(f"[DEBUG] Executing transfer to {clinic_name} at {clinic_phone}")

        # Clear pending transfer
        del call_sessions[call_sid]["pending_transfer"]
        call_sessions[call_sid]["status"] = "transferred"

        # Validate phone number format (basic US phone number validation)
        import re
        phone_clean = re.sub(r'[^\d]', '', clinic_phone)
        if len(phone_clean) == 10:
            formatted_phone = f"+1{phone_clean}"
        elif len(phone_clean) == 11 and phone_clean.startswith('1'):
            formatted_phone = f"+{phone_clean}"
        else:
            formatted_phone = clinic_phone  # Use as-is if format unclear

        print(f"[DEBUG] Formatted phone number: {formatted_phone}")

        # Return TwiML to dial the clinic
        twiml_response = f"""<?xml version="1.0" encoding="UTF-8"?>
        <Response>
            <Say>Connecting you to {clinic_name} now.</Say>
            <Dial timeout="30" callerId="{caller_number}">
                <Number>{formatted_phone}</Number>
            </Dial>
            <Say>I'm sorry, {clinic_name} didn't answer. Please try calling them directly at {clinic_phone}. You can also visit them at their location. Have a great day!</Say>
        </Response>"""

        return Response(content=twiml_response, media_type="text/xml")

    # Initialize call session for new calls
    if call_sid not in call_sessions:
        call_sessions[call_sid] = {
            "status": "connecting",
            "caller_number": caller_number,
            "conversation": [],
            "current_clinic": None,
            "calculating": False,
            "claude_analysis": {},
            "created_at": time.time(),
            "last_activity": time.time(),
            "total_messages": 0,
            "session_metadata": {
                "user_location": None,
                "service_needed": None,
                "eligibility_status": None,
                "clinic_preferences": []
            }
        }

    # Return ConversationRelay TwiML for new calls
    ws_url = os.environ.get("WEBSOCKET_URL", "wss://your-ngrok-url.ngrok.io/ws")

    twiml_response = f"""<?xml version="1.0" encoding="UTF-8"?>
    <Response>
        <Connect>
            <ConversationRelay url="{ws_url}"
                              welcomeGreeting="Hi, I'm Call2Well. Describe your situation and I'll find free care near you." />
        </Connect>
    </Response>"""

    print(f"[DEBUG] Returning TwiML with WebSocket URL: {ws_url}")
    return Response(content=twiml_response, media_type="text/xml")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    ConversationRelay WebSocket endpoint.
    Handles bidirectional conversation with Claude pipeline.
    """
    print("[DEBUG] WebSocket connection attempt")
    await websocket.accept()
    print("[DEBUG] WebSocket connection accepted")

    # Initialize Claude session
    claude_session = Call2WellSession()
    call_sid = None

    try:
        while True:
            # Receive message from ConversationRelay
            print("[DEBUG] Waiting for WebSocket message...")
            data = await websocket.receive_text()
            print(f"[DEBUG] Received WebSocket message: {data}")

            try:
                message = json.loads(data)
                print(f"[DEBUG] Parsed message: {message}")
            except json.JSONDecodeError as e:
                print(f"[DEBUG] JSON parse error: {e}")
                continue

            # Extract call info from setup message or regular messages
            if not call_sid and ("call_sid" in message or "callSid" in message):
                call_sid = message.get("callSid") or message.get("call_sid")
                print(f"[DEBUG] Set call_sid: {call_sid}")
                if call_sid in call_sessions:
                    call_sessions[call_sid]["status"] = "connected"
                    print(f"[DEBUG] Updated call session status to connected")

                    # Broadcast call connected update
                    await broadcast_to_dashboards({
                        "type": "call_connected",
                        "call_sid": call_sid,
                        "caller_number": call_sessions[call_sid].get("caller_number"),
                        "status": "connected",
                        "timestamp": time.time()
                    })

            # Handle user speech (ConversationRelay sends "prompt" type)
            if message.get("type") == "prompt":
                user_text = message.get("voicePrompt", "")
                print(f"[DEBUG] User speech received: '{user_text}'")

                # Deduplication: Create message key with call_sid + text + 5-second time window
                current_time = time.time()
                time_bucket = int(current_time // 5)  # 5-second buckets
                message_key = f"{call_sid}:{user_text}:{time_bucket}"

                # Check if this message was recently processed
                if message_key in processed_messages:
                    print(f"[DEBUG] DUPLICATE MESSAGE DETECTED - Skipping: '{user_text}'")
                    continue

                # Store this message as processed
                processed_messages[message_key] = current_time
                print(f"[DEBUG] Message deduplicated and stored: {message_key}")

                # Periodic cleanup of old messages (every 60 seconds)
                global last_cleanup
                if current_time - last_cleanup > 60:
                    cleanup_cutoff = current_time - 300  # Remove messages older than 5 minutes
                    old_keys = [k for k, timestamp in processed_messages.items() if timestamp < cleanup_cutoff]
                    for key in old_keys:
                        del processed_messages[key]
                    last_cleanup = current_time
                    print(f"[DEBUG] Cleaned up {len(old_keys)} old message keys")

                # Set calculating state
                if call_sid and call_sid in call_sessions:
                    call_sessions[call_sid]["calculating"] = True

                # Process through Claude pipeline
                print(f"[DEBUG] Sending to Claude pipeline...")
                response = claude_session.process(user_text)
                print(f"[DEBUG] Claude response: {response}")

                # Clear calculating state
                if call_sid and call_sid in call_sessions:
                    call_sessions[call_sid]["calculating"] = False

                # Update call session state with enhanced format
                if call_sid and call_sid in call_sessions:
                    user_message_id = str(uuid.uuid4())
                    assistant_message_id = str(uuid.uuid4())
                    message_timestamp = current_time

                    call_sessions[call_sid]["conversation"].append({
                        "id": user_message_id,
                        "role": "user",
                        "content": user_text,
                        "timestamp": message_timestamp
                    })
                    call_sessions[call_sid]["conversation"].append({
                        "id": assistant_message_id,
                        "role": "assistant",
                        "content": response.get("response_text", ""),
                        "timestamp": message_timestamp + 1  # Slight offset for assistant response
                    })

                    # Update session metadata
                    call_sessions[call_sid]["last_activity"] = current_time
                    call_sessions[call_sid]["total_messages"] += 2  # User + assistant message

                    # Update metadata from Claude analysis
                    if claude_session.call_state.get("user_zip"):
                        call_sessions[call_sid]["session_metadata"]["user_location"] = claude_session.call_state.get("user_zip")
                    if response.get("action"):
                        # Infer service type from conversation context
                        if any(word in user_text.lower() for word in ["tooth", "dental", "teeth"]):
                            call_sessions[call_sid]["session_metadata"]["service_needed"] = "dental"
                        elif any(word in user_text.lower() for word in ["mental", "depression", "anxiety"]):
                            call_sessions[call_sid]["session_metadata"]["service_needed"] = "mental_health"
                        elif any(word in user_text.lower() for word in ["eye", "vision", "glasses"]):
                            call_sessions[call_sid]["session_metadata"]["service_needed"] = "vision"
                        else:
                            call_sessions[call_sid]["session_metadata"]["service_needed"] = "primary_care"

                    # Update eligibility status based on income
                    monthly_income = claude_session.call_state.get("monthly_income")
                    if monthly_income:
                        if monthly_income <= 1732:  # 138% FPL
                            call_sessions[call_sid]["session_metadata"]["eligibility_status"] = "medicaid_eligible"
                        elif monthly_income <= 2510:  # 200% FPL
                            call_sessions[call_sid]["session_metadata"]["eligibility_status"] = "fqhc_eligible"
                        else:
                            call_sessions[call_sid]["session_metadata"]["eligibility_status"] = "sliding_scale_only"
                    call_sessions[call_sid]["claude_analysis"] = {
                        "action": response.get("action"),
                        "user_zip": claude_session.call_state.get("user_zip"),
                        "monthly_income": claude_session.call_state.get("monthly_income"),
                        "language": claude_session.call_state.get("language"),
                        "candidates": claude_session.call_state.get("candidates", [])
                    }
                    if response.get("clinic"):
                        call_sessions[call_sid]["current_clinic"] = response["clinic"]

                    # Broadcast conversation update to dashboard
                    await broadcast_to_dashboards({
                        "type": "conversation_update",
                        "call_sid": call_sid,
                        "latest_messages": call_sessions[call_sid]["conversation"][-2:],  # Last user + assistant
                        "claude_analysis": call_sessions[call_sid]["claude_analysis"],
                        "status": call_sessions[call_sid]["status"],
                        "calculating": call_sessions[call_sid]["calculating"],
                        "session_metadata": call_sessions[call_sid]["session_metadata"],
                        "total_messages": call_sessions[call_sid]["total_messages"],
                        "call_duration": current_time - call_sessions[call_sid]["created_at"],
                        "timestamp": current_time
                    })

                # Handle actions
                action = response.get("action")

                if action == "call_911":
                    # Emergency - disconnect and let user call 911
                    await websocket.send_text(json.dumps({
                        "type": "text",
                        "token": response.get("response_text"),
                        "last": True
                    }))
                    break

                elif action == "transfer_call":
                    # Transfer call to clinic
                    clinic = response.get("clinic")
                    if clinic and clinic.get("phone"):
                        print(f"[DEBUG] Initiating transfer to {clinic['name']} at {clinic['phone']}")

                        # Send confirmation message
                        await websocket.send_text(json.dumps({
                            "type": "text",
                            "token": f"Connecting you to {clinic['name']} now. Please hold.",
                            "last": True
                        }))

                        # For ConversationRelay transfer, we need to end the connection
                        # and redirect the call using Twilio's standard dial method
                        # This requires a callback to the voice webhook with transfer info

                        # Store transfer info for webhook callback
                        if call_sid and call_sid in call_sessions:
                            call_sessions[call_sid]["pending_transfer"] = {
                                "clinic_name": clinic["name"],
                                "clinic_phone": clinic["phone"]
                            }

                        # Send disconnect message to trigger transfer
                        await websocket.send_text(json.dumps({
                            "type": "disconnect",
                            "reason": "transfer"
                        }))

                        # Update call session
                        if call_sid and call_sid in call_sessions:
                            call_sessions[call_sid]["status"] = "transferred"
                            call_sessions[call_sid]["transferred_to"] = clinic["name"]
                            call_sessions[call_sid]["transfer_number"] = clinic["phone"]

                            # Broadcast transfer update
                            await broadcast_to_dashboards({
                                "type": "call_status_change",
                                "call_sid": call_sid,
                                "status": "transferred",
                                "clinic": clinic,
                                "timestamp": time.time()
                            })

                        print(f"[DEBUG] Transfer initiated to {clinic['phone']}")
                        break
                    else:
                        print(f"[DEBUG] Transfer failed - no clinic phone number")
                        print(f"[DEBUG] Clinic data: {clinic}")
                        await websocket.send_text(json.dumps({
                            "type": "text",
                            "token": "I'm sorry, I don't have a phone number for that clinic. Let me try to find their contact information or send you what details I have.",
                            "last": True
                        }))

                        # Try to send SMS with available clinic info if we have it
                        if clinic and call_sid and call_sid in call_sessions:
                            caller_number = call_sessions[call_sid].get("caller_number")
                            if caller_number:
                                clinic_info = f"Call2Well: {clinic.get('name', 'Clinic')}\n{clinic.get('address', 'Address not available')}"
                                try:
                                    twilio_client.messages.create(
                                        body=clinic_info,
                                        from_=os.environ["TWILIO_PHONE_NUMBER"],
                                        to=caller_number
                                    )
                                    await websocket.send_text(json.dumps({
                                        "type": "text",
                                        "token": "I've sent you what information I have about the clinic.",
                                        "last": True
                                    }))
                                except Exception as e:
                                    print(f"[DEBUG] SMS fallback failed: {e}")

                elif action == "send_sms":
                    # Send clinic details via SMS
                    clinic = response.get("clinic")
                    caller_number = call_sessions.get(call_sid, {}).get("caller_number")

                    if clinic and caller_number:
                        sms_body = (
                            f"Call2Well: {clinic['name']}\n"
                            f"{clinic.get('address', '')}\n"
                            f"{clinic.get('phone', '')}\n"
                            f"Bring: photo ID + proof of income"
                        )

                        try:
                            twilio_client.messages.create(
                                body=sms_body,
                                from_=os.environ["TWILIO_PHONE_NUMBER"],
                                to=caller_number
                            )

                            await websocket.send_text(json.dumps({
                                "type": "text",
                                "token": "I've sent the clinic details to your phone. Have a good day!",
                                "last": True
                            }))

                            # Update call session
                            if call_sid and call_sid in call_sessions:
                                call_sessions[call_sid]["status"] = "sms_sent"

                                # Broadcast SMS sent update
                                await broadcast_to_dashboards({
                                    "type": "call_status_change",
                                    "call_sid": call_sid,
                                    "status": "sms_sent",
                                    "clinic": clinic,
                                    "timestamp": time.time()
                                })
                            break

                        except Exception as e:
                            print(f"SMS send error: {e}")
                            await websocket.send_text(json.dumps({
                                "type": "text",
                                "token": "I had trouble sending the text. Let me try again - would you like me to connect you directly instead?",
                                "last": True
                            }))
                else:
                    # Continue conversation
                    response_text = response.get("response_text", "I'm sorry, I didn't understand that.")
                    print(f"[DEBUG] Sending response to user: '{response_text}'")
                    await websocket.send_text(json.dumps({
                        "type": "text",
                        "token": response_text,
                        "last": True
                    }))
                    print(f"[DEBUG] Response sent successfully")

    except WebSocketDisconnect:
        print(f"[DEBUG] WebSocket disconnected for call_sid: {call_sid}")
        if call_sid and call_sid in call_sessions:
            call_sessions[call_sid]["status"] = "disconnected"
    except Exception as e:
        print(f"[DEBUG] WebSocket error: {e}")
        print(f"[DEBUG] Error type: {type(e)}")
        if call_sid and call_sid in call_sessions:
            call_sessions[call_sid]["status"] = "error"


@app.websocket("/dashboard")
async def dashboard_websocket(websocket: WebSocket):
    """
    Dashboard WebSocket endpoint for real-time conversation updates.
    """
    print("[DEBUG] Dashboard WebSocket connection attempt")
    await websocket.accept()
    connected_dashboards.add(websocket)
    print(f"[DEBUG] Dashboard connected. Total dashboards: {len(connected_dashboards)}")

    try:
        while True:
            # Keep connection alive - receive heartbeat or other commands
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                if message.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except json.JSONDecodeError:
                pass  # Ignore malformed messages
    except WebSocketDisconnect:
        print("[DEBUG] Dashboard WebSocket disconnected")
        connected_dashboards.discard(websocket)
        print(f"[DEBUG] Dashboard disconnected. Remaining: {len(connected_dashboards)}")
    except Exception as e:
        print(f"[DEBUG] Dashboard WebSocket error: {e}")
        connected_dashboards.discard(websocket)


async def broadcast_to_dashboards(data: dict):
    """
    Broadcast data to all connected dashboard clients.
    """
    if not connected_dashboards:
        return

    print(f"[DEBUG] Broadcasting to {len(connected_dashboards)} dashboards: {data.get('type', 'unknown')}")
    dead_connections = set()

    message = json.dumps(data)
    for websocket in connected_dashboards:
        try:
            await websocket.send_text(message)
        except Exception as e:
            print(f"[DEBUG] Failed to send to dashboard: {e}")
            dead_connections.add(websocket)

    # Clean up dead connections
    if dead_connections:
        connected_dashboards.difference_update(dead_connections)
        print(f"[DEBUG] Cleaned up {len(dead_connections)} dead dashboard connections")


@app.get("/call-state/{call_sid}")
async def get_call_state(call_sid: str):
    """
    Dashboard endpoint to get current call state.
    """
    if call_sid not in call_sessions:
        return {"error": "Call not found"}

    return call_sessions[call_sid]


@app.get("/active-calls")
async def get_active_calls():
    """
    Dashboard endpoint to list active calls.
    """
    active_statuses = ["connecting", "connected", "in_progress"]
    ended_statuses = ["disconnected", "transferred", "sms_sent", "completed", "error"]

    active_calls = []
    ended_calls = []

    for sid, state in call_sessions.items():
        call_info = {
            "call_sid": sid,
            "status": state["status"],
            "caller": state.get("caller_number", "Unknown")
        }

        if state["status"] in active_statuses:
            active_calls.append(call_info)
        elif state["status"] in ended_statuses:
            ended_calls.append(call_info)

    # Return active calls first, then recent ended calls (last 5)
    all_calls = active_calls + ended_calls[-5:]

    return {
        "calls": all_calls
    }


@app.post("/outbound-call")
async def create_outbound_call():
    """
    Create an outbound call using Twilio for testing.
    Hardcoded to a test number for development.
    """
    # Hardcoded test phone number
    test_phone_number = "+16267806708"  # Your phone number

    try:
        # Extract ngrok URL from WEBSOCKET_URL
        websocket_url = os.environ.get("WEBSOCKET_URL", "")
        if "ngrok" in websocket_url:
            # Extract the domain from wss://domain.ngrok-free.dev/ws
            ngrok_domain = websocket_url.split("://")[1].split("/")[0]
            webhook_url = f"https://{ngrok_domain}/voice"
        else:
            # Fallback to localhost (won't work for actual Twilio calls)
            webhook_url = "http://localhost:8000/voice"

        print(f"[DEBUG] Using webhook URL: {webhook_url}")

        # Create outbound call using Twilio
        call = twilio_client.calls.create(
            to=test_phone_number,
            from_=os.environ["TWILIO_PHONE_NUMBER"],
            url=webhook_url,
            method="POST"
        )

        call_sid = call.sid
        print(f"[DEBUG] Created outbound call: {call_sid} to {test_phone_number}")

        # Initialize call session for outbound call
        if call_sid not in call_sessions:
            call_sessions[call_sid] = {
                "session": None,
                "status": "connecting",
                "caller_number": test_phone_number,
                "conversation": [],
                "created_at": time.time(),
                "last_activity": time.time(),
                "total_messages": 0,
                "claude_analysis": {},
                "session_metadata": {
                    "call_type": "outbound_test"
                },
                "calculating": False,
                "current_clinic": None
            }

        # Broadcast call connected update
        await broadcast_to_dashboards({
            "type": "call_connected",
            "call_sid": call_sid,
            "caller_number": test_phone_number,
            "call_type": "outbound"
        })

        return {
            "success": True,
            "call_sid": call_sid,
            "to_number": test_phone_number,
            "message": "Outbound call initiated successfully"
        }

    except Exception as e:
        error_msg = f"Failed to create outbound call: {str(e)}"
        print(f"[ERROR] {error_msg}")
        return {
            "success": False,
            "error": error_msg
        }


@app.delete("/clear-sessions")
async def clear_sessions():
    """
    Clear all stored call sessions and related data.
    Returns count of cleared sessions and broadcasts update to dashboards.
    """
    global call_sessions, processed_messages

    # Count sessions before clearing
    total_sessions = len(call_sessions)
    active_sessions = len([s for s in call_sessions.values() if s.get("status") in ["connecting", "connected", "in_progress"]])
    ended_sessions = total_sessions - active_sessions

    print(f"[DEBUG] Clearing {total_sessions} sessions ({active_sessions} active, {ended_sessions} ended)")

    # Clear all session data
    call_sessions.clear()
    processed_messages.clear()

    # Broadcast to all connected dashboards
    await broadcast_to_dashboards({
        "type": "sessions_cleared",
        "cleared_count": total_sessions,
        "active_cleared": active_sessions,
        "ended_cleared": ended_sessions,
        "timestamp": time.time()
    })

    print(f"[DEBUG] Successfully cleared all sessions and notified dashboards")

    return {
        "success": True,
        "message": f"Cleared {total_sessions} sessions",
        "details": {
            "total_cleared": total_sessions,
            "active_sessions_cleared": active_sessions,
            "ended_sessions_cleared": ended_sessions
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)