"""
MuleOps Intelligence Demo Broker — Slack Relay
Thin relay: receives Slack events → forwards to Mule Agent Fabric broker via A2A → posts response back to Slack.
All routing, multi-agent orchestration, compliance checks, and ADO log writes are handled by the
MuleSoft Agent Fabric broker on CloudHub (accessed through Flex Gateway). This process does nothing
except Slack I/O and OBO token construction.
"""
import os
import json
import uuid
import re
import base64
import logging
import asyncio
import requests
import httpx
from datetime import datetime, timezone
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────────────

# Mule Agent Fabric broker exposed through Flex Gateway on CloudHub
MULE_BROKER_URL = os.environ.get(
    "MULE_BROKER_URL",
    "https://mia-integration-gateway-b1r8p2.5sc6y6-1.usa-e2.cloudhub.io/muleops_intelligence_broker"
)

# Slack Bot OAuth Token — set via environment variable
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
if not SLACK_BOT_TOKEN:
    raise RuntimeError("SLACK_BOT_TOKEN environment variable is required")

# Track processed Slack event IDs to prevent duplicate processing
PROCESSED_EVENTS: set = set()

app = FastAPI(title="MuleOps Intelligence Demo Broker", version="2.0.0")


class BrokerRequest(BaseModel):
    query: str


# ── OBO Token ────────────────────────────────────────────────────────────────

def build_obo_token(slack_user_id: str, channel: str) -> str:
    """Build a base64-encoded OBO audit token from Slack user identity.
    Forwarded to the Mule broker so Flex Gateway policies can inspect the caller.
    """
    payload = {
        "slack_user_id": slack_user_id,
        "channel": channel,
        "initiated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "slack"
    }
    return base64.b64encode(json.dumps(payload).encode()).decode()


# ── Mule Agent Fabric call ────────────────────────────────────────────────────

def call_mule_broker(query: str, obo_token: str = None, initiated_by: str = None) -> dict:
    """
    Send query to the Mule Agent Fabric broker via A2A JSON-RPC tasks/send.
    The broker (Gemini Flash + Agent Fabric) handles all routing, multi-agent
    orchestration, compliance checks, and ADO log writes internally.

    Returns a dict with correlationId, response text, and timestamp.
    """
    correlation_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())

    message_id = str(uuid.uuid4())
    payload = {
        "jsonrpc": "2.0",
        "method": "message/send",
        "id": correlation_id,
        "params": {
            "message": {
                "messageId": message_id,
                "kind": "message",
                "role": "user",
                "parts": [{"kind": "text", "text": query}]
            }
        }
    }
    headers = {
        "Content-Type": "application/json",
        "X-Correlation-ID": correlation_id
    }
    if obo_token:
        headers["X-OBO-Token"] = obo_token
    if initiated_by:
        headers["X-Initiated-By"] = initiated_by

    logger.info(
        f"[RELAY] → Mule broker | CorrelationID: {correlation_id}"
        + (f" | User: {initiated_by}" if initiated_by else "")
        + f" | Query: {query[:80]}"
    )

    try:
        r = requests.post(
            MULE_BROKER_URL,
            json=payload,
            headers=headers,
            timeout=120  # Agent Fabric multi-agent queries can take 15–30s
        )
        r.raise_for_status()
        data = r.json()

        # Extract response text from A2A v0.3.0 task reply envelope
        result = data.get("result", {})
        # Primary: status.message.parts (broker final message)
        response_text = (
            result.get("status", {})
                  .get("message", {})
                  .get("parts", [{}])[0]
                  .get("text", "")
        )
        if not response_text:
            # Fallback: artifacts (completed tasks)
            response_text = (
                result.get("artifacts", [{}])[0]
                      .get("parts", [{}])[0]
                      .get("text", "")
            )
        if not response_text:
            response_text = "No response received from broker."

        logger.info(f"[RELAY] ← Mule broker responded | CorrelationID: {correlation_id}")

    except requests.exceptions.Timeout:
        response_text = (
            "⏱️ The broker timed out. The query may still be processing — "
            "please try again or check the CloudHub application logs."
        )
        logger.error(f"[RELAY] Mule broker timeout | CorrelationID: {correlation_id}")

    except Exception as e:
        response_text = f"⚠️ Broker call failed: {str(e)[:200]}"
        logger.error(f"[RELAY] Mule broker error: {str(e)[:200]} | CorrelationID: {correlation_id}")

    return {
        "correlationId": correlation_id,
        "query": query,
        "routedTo": "mule-agent-fabric-broker",
        "initiatedBy": initiated_by or "api-direct",
        "response": response_text,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    }


# ── Formatting ────────────────────────────────────────────────────────────────

def markdown_to_slack(text: str) -> str:
    """Convert Gemini/Agent Fabric markdown to Slack mrkdwn format."""
    # **bold** → *bold*
    text = re.sub(r'\*\*(.+?)\*\*', r'*\1*', text)
    # __italic__ → _italic_
    text = re.sub(r'__(.+?)__', r'_\1_', text)
    # Remove horizontal rules (--- or ***)
    text = re.sub(r'^\s*[-*]{3,}\s*$', '', text, flags=re.MULTILINE)
    # * bullet or - bullet at line start → • bullet
    text = re.sub(r'^\s*[\*\-]\s+', '• ', text, flags=re.MULTILINE)
    # Remove stray trailing asterisk
    text = re.sub(r'\.\*\s*$', '.', text.rstrip())
    # Collapse 3+ blank lines into 2
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ── Slack helpers ─────────────────────────────────────────────────────────────

async def post_to_slack(channel: str, text: str) -> None:
    """Post a message to a Slack channel using chat.postMessage."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://slack.com/api/chat.postMessage",
                headers={
                    "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
                    "Content-Type": "application/json"
                },
                json={"channel": channel, "text": text}
            )
            data = resp.json()
            if not data.get("ok"):
                logger.error(f"[SLACK] chat.postMessage failed: {data.get('error')}")
            else:
                logger.info(f"[SLACK] Message posted to {channel}")
    except Exception as e:
        logger.error(f"[SLACK] Failed to post message: {str(e)[:200]}")


async def handle_slack_event(event: dict, channel: str) -> None:
    """
    Process a Slack event:
      1. Strip the @mention from the text
      2. Forward the query to the Mule broker via A2A (call_mule_broker)
      3. Post the formatted response + audit footer back to Slack
    """
    try:
        text = event.get("text", "")
        # Remove the bot mention token <@XXXXX>
        if "<@" in text:
            text = text.split(">", 1)[-1].strip()

        if not text:
            await post_to_slack(channel, "Sorry, I didn't catch your question. Please try again!")
            return

        slack_user_id = event.get("user", "unknown")
        obo_token = build_obo_token(slack_user_id, channel)
        logger.info(f"[SLACK] Query from {channel}: {text[:100]} | User: {slack_user_id}")

        # Immediate acknowledgement so Slack shows the bot is working
        await post_to_slack(channel, "🔍 Processing your query via MuleSoft Agent Fabric...")

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, call_mule_broker, text, obo_token, slack_user_id
        )

        response = result.get("response", "Sorry, I couldn't get a response.")
        correlation_id = result.get("correlationId", "")

        slack_text = markdown_to_slack(response)

        # Append audit trail footer — governance visibility without clutter
        if slack_user_id and slack_user_id != "unknown":
            ref = correlation_id[:8] if correlation_id else "n/a"
            audit_footer = (
                f"\n\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"_🔍 User: {slack_user_id}  |  Ref: {ref}_"
            )
            slack_text = slack_text + audit_footer

        await post_to_slack(channel, slack_text)

    except Exception as e:
        logger.error(f"[SLACK] Error handling event: {str(e)[:200]}")
        await post_to_slack(channel, f"⚠️ Sorry, something went wrong: {str(e)[:100]}")


# ── REST Endpoints ────────────────────────────────────────────────────────────

@app.post("/api/broker")
async def broker(request: BrokerRequest):
    """Direct REST endpoint for testing without Slack."""
    result = call_mule_broker(request.query)
    return JSONResponse(result)


@app.post("/api/slack/events")
async def slack_events(request: Request, background_tasks: BackgroundTasks):
    """
    Slack Events API endpoint.
    Handles:
      - url_verification challenge (Slack app setup)
      - app_mention events (when @MuleOps is mentioned in a channel)
      - message.im events (direct messages to the bot)
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    event_type = body.get("type")

    # Slack sends a one-time challenge when you register the Events URL
    if event_type == "url_verification":
        logger.info("[SLACK] Responding to url_verification challenge")
        return JSONResponse({"challenge": body.get("challenge")})

    if event_type == "event_callback":
        # Deduplicate — Slack retries if it doesn't get a 200 within 3s
        event_id = body.get("event_id", "")
        if event_id and event_id in PROCESSED_EVENTS:
            logger.info(f"[SLACK] Skipping duplicate event: {event_id}")
            return JSONResponse({"ok": True})
        if event_id:
            PROCESSED_EVENTS.add(event_id)
            if len(PROCESSED_EVENTS) > 1000:
                PROCESSED_EVENTS.clear()

        event = body.get("event", {})
        event_subtype = event.get("type")
        channel = event.get("channel", "")

        # Ignore bot's own messages to prevent echo loops
        if event.get("bot_id") or event.get("subtype") == "bot_message":
            return JSONResponse({"ok": True})

        if event_subtype == "app_mention":
            logger.info(f"[SLACK] app_mention in {channel}")
            background_tasks.add_task(handle_slack_event, event, channel)

        elif event_subtype == "message" and event.get("channel_type") == "im":
            logger.info(f"[SLACK] Direct message in {channel}")
            background_tasks.add_task(handle_slack_event, event, channel)

        return JSONResponse({"ok": True})

    logger.warning(f"[SLACK] Unknown event type: {event_type}")
    return JSONResponse({"ok": True})


@app.get("/api/health")
async def health():
    return {
        "status": "UP",
        "service": "muleops-demo-broker",
        "version": "2.0.0",
        "architecture": "slack-relay",
        "mule_broker_url": MULE_BROKER_URL
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 9000))
    print(f"\n🚀 MuleOps Intelligence Demo Broker (Slack Relay)")
    print(f"   Listening on port {port}")
    print(f"   Mule Broker URL: {MULE_BROKER_URL}\n")
    uvicorn.run(app, host="0.0.0.0", port=port)
