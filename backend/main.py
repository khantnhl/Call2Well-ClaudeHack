"""
ClearPath FastAPI server with Twilio ConversationRelay WebSocket support.

Routes:
  GET /voice - Twilio webhook returning ConversationRelay TwiML
  WebSocket /ws - ConversationRelay WebSocket endpoint
  GET /call-state/{call_sid} - Dashboard polling endpoint

Run:
  uvicorn main:app --reload --port 8000
"""

import json
import os
from typing import Dict
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from claude_pipeline import ClearPathSession
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

    # Initialize call session
    call_sessions[call_sid] = {
        "status": "connecting",
        "caller_number": caller_number,
        "conversation": [],
        "current_clinic": None,
        "claude_analysis": {}
    }

    # Return ConversationRelay TwiML (raw XML)
    ws_url = os.environ.get("WEBSOCKET_URL", "wss://your-ngrok-url.ngrok.io/ws")

    twiml_response = f"""<?xml version="1.0" encoding="UTF-8"?>
    <Response>
        <Connect>
            <ConversationRelay url="{ws_url}"
                              welcomeGreeting="Hi, I'm ClearPath. Describe your situation and I'll find free care near you." />
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
    claude_session = ClearPathSession()
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

            # Extract call info on first message
            if not call_sid and "call_sid" in message:
                call_sid = message["call_sid"]
                print(f"[DEBUG] Set call_sid: {call_sid}")
                if call_sid in call_sessions:
                    call_sessions[call_sid]["status"] = "connected"
                    print(f"[DEBUG] Updated call session status to connected")

            # Handle user speech (ConversationRelay sends "prompt" type)
            if message.get("type") == "prompt":
                user_text = message.get("voicePrompt", "")
                print(f"[DEBUG] User speech received: '{user_text}'")

                # Process through Claude pipeline
                print(f"[DEBUG] Sending to Claude pipeline...")
                response = claude_session.process(user_text)
                print(f"[DEBUG] Claude response: {response}")

                # Update call session state
                if call_sid and call_sid in call_sessions:
                    call_sessions[call_sid]["conversation"].append({
                        "role": "user",
                        "content": user_text
                    })
                    call_sessions[call_sid]["conversation"].append({
                        "role": "assistant",
                        "content": response.get("response_text", "")
                    })
                    call_sessions[call_sid]["claude_analysis"] = {
                        "action": response.get("action"),
                        "user_zip": claude_session.call_state.get("user_zip"),
                        "monthly_income": claude_session.call_state.get("monthly_income"),
                        "language": claude_session.call_state.get("language"),
                        "candidates": claude_session.call_state.get("candidates", [])
                    }
                    if response.get("clinic"):
                        call_sessions[call_sid]["current_clinic"] = response["clinic"]

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
                        await websocket.send_text(json.dumps({
                            "type": "text",
                            "token": "Connecting you now.",
                            "last": True
                        }))

                        # Update call session
                        if call_sid and call_sid in call_sessions:
                            call_sessions[call_sid]["status"] = "transferred"
                        break

                elif action == "send_sms":
                    # Send clinic details via SMS
                    clinic = response.get("clinic")
                    caller_number = call_sessions.get(call_sid, {}).get("caller_number")

                    if clinic and caller_number:
                        sms_body = (
                            f"ClearPath: {clinic['name']}\n"
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
    return {
        "calls": [
            {"call_sid": sid, "status": state["status"], "caller": state.get("caller_number")}
            for sid, state in call_sessions.items()
            if state["status"] not in ["disconnected", "transferred", "sms_sent"]
        ]
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)