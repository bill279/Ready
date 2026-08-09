import asyncio
import os
import time

import httpx
import msal

import token_store

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
SCOPES = ["Mail.ReadWrite", "Mail.Send", "Calendars.ReadWrite", "User.Read"]

# Refresh this many seconds before the access token actually expires, so a call
# that starts just under the wire doesn't fail mid-flight.
EXPIRY_SKEW = 300


class NotConnectedError(Exception):
    """No usable Outlook token for this session — the user must reconnect."""


def _get_app():
    return msal.ConfidentialClientApplication(
        client_id=os.environ["AZURE_CLIENT_ID"].strip(),
        client_credential=os.environ["AZURE_CLIENT_SECRET"].strip(),
        authority=f"https://login.microsoftonline.com/{os.environ.get('AZURE_TENANT_ID', 'common').strip()}",
    )


def get_auth_url(redirect_uri: str, state: str = "") -> str:
    app = _get_app()
    return app.get_authorization_request_url(
        scopes=SCOPES,
        redirect_uri=redirect_uri,
        state=state,
    )


def _store_result(session_id: str, result: dict) -> None:
    expires_at = time.time() + float(result.get("expires_in", 3600))
    account = (result.get("id_token_claims") or {}).get("preferred_username")
    token_store.save(
        session_id,
        access_token=result["access_token"],
        refresh_token=result.get("refresh_token"),
        expires_at=expires_at,
        account=account,
    )


def exchange_code(session_id: str, code: str, redirect_uri: str) -> dict:
    app = _get_app()
    result = app.acquire_token_by_authorization_code(
        code=code,
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )
    if "error" in result:
        raise ValueError(result.get("error_description", result["error"]))
    _store_result(session_id, result)
    return result


def _refresh(session_id: str, refresh_token: str) -> str:
    app = _get_app()
    result = app.acquire_token_by_refresh_token(refresh_token, scopes=SCOPES)
    if "error" in result or "access_token" not in result:
        # The refresh token is spent or revoked; drop it so the UI prompts a
        # reconnect instead of retrying a token that will never work.
        token_store.delete(session_id)
        raise NotConnectedError(
            result.get("error_description", "Outlook session expired. Please reconnect your account.")
        )
    _store_result(session_id, result)
    return result["access_token"]


async def _access_token(session_id: str) -> str:
    if not session_id:
        raise NotConnectedError("No session. Please connect your Outlook account first.")

    record = token_store.load(session_id)
    if not record:
        raise NotConnectedError("Not authenticated with Outlook. Please connect your account first.")

    if record["expires_at"] - EXPIRY_SKEW > time.time():
        return record["access_token"]

    if not record["refresh_token"]:
        token_store.delete(session_id)
        raise NotConnectedError("Outlook session expired. Please reconnect your account.")

    # msal is synchronous; keep it off the event loop.
    return await asyncio.to_thread(_refresh, session_id, record["refresh_token"])


async def _headers(session_id: str) -> dict:
    token = await _access_token(session_id)
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def status(session_id: str) -> dict:
    """Connection state for the UI. A refreshable session still counts as connected."""
    record = token_store.load(session_id) if session_id else None
    if not record:
        return {"outlook_connected": False}
    usable = record["expires_at"] - EXPIRY_SKEW > time.time() or bool(record["refresh_token"])
    return {
        "outlook_connected": usable,
        "account": record["account"],
        "expires_at": record["expires_at"],
    }


def disconnect(session_id: str) -> None:
    if session_id:
        token_store.delete(session_id)


async def send_email(session_id: str, to: str, subject: str, body: str) -> dict:
    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": to}}],
        },
        "saveToSentItems": True,
    }
    headers = await _headers(session_id)
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{GRAPH_BASE}/me/sendMail", json=payload, headers=headers)
        r.raise_for_status()
    return {"status": "sent", "to": to, "subject": subject}


async def list_emails(session_id: str, folder: str = "inbox", top: int = 10) -> list[dict]:
    headers = await _headers(session_id)
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{GRAPH_BASE}/me/mailFolders/{folder}/messages",
            params={"$top": top, "$orderby": "receivedDateTime desc",
                    "$select": "subject,from,receivedDateTime,isRead,bodyPreview"},
            headers=headers,
        )
        r.raise_for_status()
    return r.json().get("value", [])


async def list_calendar_events(session_id: str, top: int = 10) -> list[dict]:
    headers = await _headers(session_id)
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{GRAPH_BASE}/me/events",
            params={"$top": top, "$orderby": "start/dateTime",
                    "$select": "subject,start,end,location,organizer"},
            headers=headers,
        )
        r.raise_for_status()
    return r.json().get("value", [])


async def create_calendar_event(session_id: str, subject: str, start: str, end: str,
                                body: str = "", location: str = "") -> dict:
    payload = {
        "subject": subject,
        "body": {"contentType": "Text", "content": body},
        "start": {"dateTime": start, "timeZone": "UTC"},
        "end": {"dateTime": end, "timeZone": "UTC"},
        "location": {"displayName": location},
    }
    headers = await _headers(session_id)
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{GRAPH_BASE}/me/events", json=payload, headers=headers)
        r.raise_for_status()
    return r.json()
