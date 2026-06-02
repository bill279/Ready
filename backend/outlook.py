import os
import httpx
import msal

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

_token_cache: dict = {}


def _get_app():
    return msal.ConfidentialClientApplication(
        client_id=os.environ["AZURE_CLIENT_ID"],
        client_credential=os.environ["AZURE_CLIENT_SECRET"],
        authority=f"https://login.microsoftonline.com/{os.environ.get('AZURE_TENANT_ID', 'common')}",
    )


def get_auth_url(redirect_uri: str, state: str = "") -> str:
    app = _get_app()
    return app.get_authorization_request_url(
        scopes=["Mail.ReadWrite", "Mail.Send", "Calendars.ReadWrite", "User.Read"],
        redirect_uri=redirect_uri,
        state=state,
    )


def exchange_code(code: str, redirect_uri: str) -> dict:
    app = _get_app()
    result = app.acquire_token_by_authorization_code(
        code=code,
        scopes=["Mail.ReadWrite", "Mail.Send", "Calendars.ReadWrite", "User.Read"],
        redirect_uri=redirect_uri,
    )
    if "error" in result:
        raise ValueError(result.get("error_description", result["error"]))
    _token_cache["access_token"] = result["access_token"]
    _token_cache["refresh_token"] = result.get("refresh_token")
    return result


def _headers() -> dict:
    token = _token_cache.get("access_token")
    if not token:
        raise ValueError("Not authenticated with Outlook. Please connect your account first.")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


async def send_email(to: str, subject: str, body: str) -> dict:
    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": to}}],
        },
        "saveToSentItems": True,
    }
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{GRAPH_BASE}/me/sendMail", json=payload, headers=_headers())
        r.raise_for_status()
    return {"status": "sent", "to": to, "subject": subject}


async def list_emails(folder: str = "inbox", top: int = 10) -> list[dict]:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{GRAPH_BASE}/me/mailFolders/{folder}/messages",
            params={"$top": top, "$orderby": "receivedDateTime desc",
                    "$select": "subject,from,receivedDateTime,isRead,bodyPreview"},
            headers=_headers(),
        )
        r.raise_for_status()
    return r.json().get("value", [])


async def list_calendar_events(top: int = 10) -> list[dict]:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{GRAPH_BASE}/me/events",
            params={"$top": top, "$orderby": "start/dateTime",
                    "$select": "subject,start,end,location,organizer"},
            headers=_headers(),
        )
        r.raise_for_status()
    return r.json().get("value", [])


async def create_calendar_event(subject: str, start: str, end: str, body: str = "", location: str = "") -> dict:
    payload = {
        "subject": subject,
        "body": {"contentType": "Text", "content": body},
        "start": {"dateTime": start, "timeZone": "UTC"},
        "end": {"dateTime": end, "timeZone": "UTC"},
        "location": {"displayName": location},
    }
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{GRAPH_BASE}/me/events", json=payload, headers=_headers())
        r.raise_for_status()
    return r.json()
