import json
import os
from tavily import TavilyClient
import outlook as outlook_module

tavily = TavilyClient(api_key=os.environ.get("TAVILY_API_KEY", ""))

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "name": "web_search",
        "description": "Search the web for real-time information, news, facts, or anything that requires up-to-date data.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query"},
                "max_results": {"type": "integer", "description": "Number of results (default 5)", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "type": "function",
        "name": "send_email",
        "description": "Send an email via Outlook on behalf of the user.",
        "parameters": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string", "description": "Email subject"},
                "body": {"type": "string", "description": "Email body text"},
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "type": "function",
        "name": "list_emails",
        "description": "List recent emails from the user's Outlook inbox.",
        "parameters": {
            "type": "object",
            "properties": {
                "folder": {"type": "string", "description": "Mail folder (default: inbox)", "default": "inbox"},
                "top": {"type": "integer", "description": "Number of emails to fetch (default: 10)", "default": 10},
            },
        },
    },
    {
        "type": "function",
        "name": "list_calendar_events",
        "description": "List upcoming calendar events from the user's Outlook calendar.",
        "parameters": {
            "type": "object",
            "properties": {
                "top": {"type": "integer", "description": "Number of events to fetch (default: 10)", "default": 10},
            },
        },
    },
    {
        "type": "function",
        "name": "create_calendar_event",
        "description": "Create a new calendar event in the user's Outlook calendar.",
        "parameters": {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "Event title"},
                "start": {"type": "string", "description": "Start datetime in ISO 8601 format (e.g. 2025-01-15T09:00:00)"},
                "end": {"type": "string", "description": "End datetime in ISO 8601 format"},
                "body": {"type": "string", "description": "Event description"},
                "location": {"type": "string", "description": "Event location"},
            },
            "required": ["subject", "start", "end"],
        },
    },
]


async def execute_tool(name: str, args: dict, session_id: str = "") -> str:
    try:
        if name == "web_search":
            results = tavily.search(
                query=args["query"],
                max_results=args.get("max_results", 5),
                include_answer=True,
            )
            answer = results.get("answer", "")
            sources = [
                f"- {r['title']}: {r['url']}\n  {r.get('content', '')[:200]}"
                for r in results.get("results", [])
            ]
            return json.dumps({"answer": answer, "sources": sources})

        elif name == "send_email":
            result = await outlook_module.send_email(
                session_id, args["to"], args["subject"], args["body"]
            )
            return json.dumps(result)

        elif name == "list_emails":
            emails = await outlook_module.list_emails(
                session_id,
                folder=args.get("folder", "inbox"),
                top=args.get("top", 10),
            )
            simplified = [
                {
                    "from": e.get("from", {}).get("emailAddress", {}).get("address"),
                    "subject": e.get("subject"),
                    "received": e.get("receivedDateTime"),
                    "isRead": e.get("isRead"),
                    "preview": e.get("bodyPreview", "")[:150],
                }
                for e in emails
            ]
            return json.dumps(simplified)

        elif name == "list_calendar_events":
            events = await outlook_module.list_calendar_events(session_id, top=args.get("top", 10))
            simplified = [
                {
                    "subject": e.get("subject"),
                    "start": e.get("start", {}).get("dateTime"),
                    "end": e.get("end", {}).get("dateTime"),
                    "location": e.get("location", {}).get("displayName"),
                    "organizer": e.get("organizer", {}).get("emailAddress", {}).get("address"),
                }
                for e in events
            ]
            return json.dumps(simplified)

        elif name == "create_calendar_event":
            result = await outlook_module.create_calendar_event(
                session_id,
                subject=args["subject"],
                start=args["start"],
                end=args["end"],
                body=args.get("body", ""),
                location=args.get("location", ""),
            )
            return json.dumps({"status": "created", "id": result.get("id"), "subject": result.get("subject")})

        else:
            return json.dumps({"error": f"Unknown tool: {name}"})

    except outlook_module.NotConnectedError as e:
        return json.dumps({"error": str(e), "needs_auth": True})

    except Exception as e:
        return json.dumps({"error": str(e)})
