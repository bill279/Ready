import os
import json
import asyncio
import httpx
import websockets
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from dotenv import load_dotenv

load_dotenv()

import tools as tool_module
import outlook as outlook_module
import token_store

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Touch the store at boot so a broken TOKEN_DB_PATH surfaces here, not on
    # the first email the assistant tries to send.
    await asyncio.to_thread(token_store.purge_stale)
    yield


app = FastAPI(title="Executive Assistant API", lifespan=lifespan)

FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")

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


REQUIRED_ENV = ["OPENAI_API_KEY", "TAVILY_API_KEY", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET"]


@app.get("/health")
async def health(deep: bool = False):
    """Report what the assistant actually needs to work.

    Default is config-only so Render's health check stays cheap; ?deep=true
    additionally verifies the OpenAI key against the live API.
    """
    checks: dict = {}
    healthy = True

    missing = [name for name in REQUIRED_ENV if not os.environ.get(name, "").strip()]
    checks["config"] = "ok" if not missing else f"missing: {', '.join(missing)}"
    if missing:
        healthy = False

    try:
        checks["token_store"] = {"status": "ok", **token_store.stats()}
    except Exception as e:
        checks["token_store"] = {"status": "error", "detail": str(e)}
        healthy = False

    if deep:
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                r = await client.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                )
            if r.status_code == 200:
                checks["openai_api"] = "ok"
            else:
                checks["openai_api"] = f"http {r.status_code}"
                healthy = False
        except Exception as e:
            checks["openai_api"] = f"unreachable: {e}"
            healthy = False

    body = {"status": "ok" if healthy else "degraded", "checks": checks}
    return JSONResponse(body, status_code=200 if healthy else 503)


@app.get("/auth/outlook")
async def outlook_auth(session: str = ""):
    # Redirect URI points to frontend — avoids Safari rejecting long backend URLs.
    # The session id rides along in `state` so the callback binds the tokens to
    # the browser that actually started the flow.
    redirect_uri = FRONTEND_URL.rstrip("/") + "/auth/callback"
    url = outlook_module.get_auth_url(redirect_uri, state=session)
    return RedirectResponse(url)


@app.post("/auth/outlook/exchange")
async def outlook_exchange(body: dict):
    code = body.get("code", "")
    session = (body.get("session") or "").strip()
    if not code:
        return JSONResponse({"error": "missing code"}, status_code=400)
    if not session:
        return JSONResponse({"error": "missing session"}, status_code=400)
    redirect_uri = FRONTEND_URL.rstrip("/") + "/auth/callback"
    try:
        await asyncio.to_thread(outlook_module.exchange_code, session, code, redirect_uri)
        return {"status": "connected", **outlook_module.status(session)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.get("/auth/status")
async def auth_status(session: str = ""):
    return outlook_module.status(session.strip())


@app.post("/auth/disconnect")
async def auth_disconnect(body: dict):
    outlook_module.disconnect((body.get("session") or "").strip())
    return {"status": "disconnected"}


@app.websocket("/ws/realtime")
async def realtime_proxy(client_ws: WebSocket):
    await client_ws.accept()
    session_id = client_ws.query_params.get("session", "").strip()

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
                            result = await tool_module.execute_tool(fn_name, args, session_id)

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
