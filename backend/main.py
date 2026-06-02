import os
import json
import asyncio
import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from dotenv import load_dotenv

load_dotenv()

import tools as tool_module
import outlook as outlook_module

app = FastAPI(title="Executive Assistant API")

FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
REALTIME_URL = "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-12-17"

SYSTEM_PROMPT = """You are an elite executive assistant. You are concise, professional, and proactive.

Your capabilities:
- Answer any question with real-time web search when needed
- Send emails via Outlook on the user's behalf
- Check and manage calendar events
- Read emails from inbox

Guidelines:
- Always confirm before sending emails or creating events
- Be conversational and natural in voice responses
- Keep voice responses brief and clear — no long lists or markdown
- Use web search for any current events, prices, weather, news, or facts
- When asked to send an email, draft it first and confirm with the user
"""


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/auth/outlook")
async def outlook_auth(request: Request):
    redirect_uri = str(request.base_url) + "auth/outlook/callback"
    url = outlook_module.get_auth_url(redirect_uri)
    return RedirectResponse(url)


@app.get("/auth/outlook/callback")
async def outlook_callback(request: Request, code: str = "", error: str = ""):
    if error:
        return JSONResponse({"error": error}, status_code=400)
    redirect_uri = str(request.base_url) + "auth/outlook/callback"
    try:
        outlook_module.exchange_code(code, redirect_uri)
        return RedirectResponse(f"{FRONTEND_URL}?outlook=connected")
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.get("/auth/status")
async def auth_status():
    return {"outlook_connected": bool(outlook_module._token_cache.get("access_token"))}


@app.websocket("/ws/realtime")
async def realtime_proxy(client_ws: WebSocket):
    await client_ws.accept()

    openai_headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "OpenAI-Beta": "realtime=v1",
    }

    try:
        async with websockets.connect(REALTIME_URL, additional_headers=openai_headers) as openai_ws:
            # Send session configuration
            session_config = {
                "type": "session.update",
                "session": {
                    "modalities": ["text", "audio"],
                    "instructions": SYSTEM_PROMPT,
                    "voice": "alloy",
                    "input_audio_format": "pcm16",
                    "output_audio_format": "pcm16",
                    "input_audio_transcription": {"model": "whisper-1"},
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": 0.5,
                        "prefix_padding_ms": 300,
                        "silence_duration_ms": 700,
                    },
                    "tools": tool_module.TOOL_DEFINITIONS,
                    "tool_choice": "auto",
                    "temperature": 0.8,
                },
            }
            await openai_ws.send(json.dumps(session_config))

            async def client_to_openai():
                try:
                    while True:
                        data = await client_ws.receive_text()
                        await openai_ws.send(data)
                except (WebSocketDisconnect, Exception):
                    pass

            async def openai_to_client():
                try:
                    async for message in openai_ws:
                        event = json.loads(message)
                        event_type = event.get("type", "")

                        # Handle tool calls
                        if event_type == "response.function_call_arguments.done":
                            fn_name = event.get("name", "")
                            call_id = event.get("call_id", "")
                            try:
                                args = json.loads(event.get("arguments", "{}"))
                            except json.JSONDecodeError:
                                args = {}

                            # Forward the event to client so UI can show tool activity
                            await client_ws.send_text(message)

                            # Execute tool
                            result = await tool_module.execute_tool(fn_name, args)

                            # Send result back to OpenAI
                            tool_result = {
                                "type": "conversation.item.create",
                                "item": {
                                    "type": "function_call_output",
                                    "call_id": call_id,
                                    "output": result,
                                },
                            }
                            await openai_ws.send(json.dumps(tool_result))
                            await openai_ws.send(json.dumps({"type": "response.create"}))
                        else:
                            await client_ws.send_text(message)
                except Exception:
                    pass

            await asyncio.gather(client_to_openai(), openai_to_client())

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await client_ws.send_text(json.dumps({"type": "error", "message": str(e)}))
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
