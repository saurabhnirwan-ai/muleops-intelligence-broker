"""
PagerDuty Specialist Agent — A2A FastAPI Application
Uses Google Gemini with automatic key rotation (primary → fallback on quota error).
"""
import os
import json
import uuid
import logging
import google.generativeai as genai
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pagerduty_tools import PagerDutyTools
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

PRIMARY_KEY = os.environ.get("GEMINI_API_KEY")
FALLBACK_KEY = os.environ.get("GEMINI_API_KEY_FALLBACK")

app = FastAPI(title="MuleOps PagerDuty Specialist Agent", version="1.0.0")
pd_tools = PagerDutyTools(api_token=os.environ.get("PAGERDUTY_API_TOKEN"))

SYSTEM_PROMPT = """You are a PagerDuty specialist agent for a MuleSoft operations team.
You help ops engineers by answering questions about incidents, on-call schedules,
escalation policies, and PagerDuty services.
Always include incident IDs, timestamps, and status in your responses.
Format lists with bullet points. Be concise but complete."""


class A2AMessage(BaseModel):
    role: str
    parts: list
    messageId: str = None   # present in message/send (A2A v0.3.0), absent in tasks/send
    kind: str = None        # present in message/send

class A2AParams(BaseModel):
    id: str = None          # present in tasks/send, absent in message/send
    message: A2AMessage

class A2ARequest(BaseModel):
    jsonrpc: str = "2.0"
    method: str
    id: str
    params: A2AParams


def get_gemini_model(api_key: str):
    genai.configure(api_key=api_key)
    return genai.GenerativeModel("gemini-3.5-flash-lite")


def call_gemini_with_fallback(prompt: str) -> str:
    """Call Gemini with automatic fallback to second key on quota errors."""
    keys = [k for k in [PRIMARY_KEY, FALLBACK_KEY] if k]
    last_error = None
    for key in keys:
        try:
            m = get_gemini_model(key)
            response = m.generate_content(prompt)
            return response.text
        except Exception as e:
            if "429" in str(e) or "quota" in str(e).lower():
                logger.warning(f"[PagerDuty Agent] Quota exceeded on key ending ...{key[-6:]} — trying next key")
                last_error = e
                continue
            raise e
    raise last_error or Exception("All Gemini API keys exhausted")


@app.post("/")
@app.post("/a2a")
async def handle_a2a(http_request: Request, request: A2ARequest):
    # Extract OBO audit headers forwarded by the broker
    obo_token = http_request.headers.get("X-OBO-Token", "")
    initiated_by = http_request.headers.get("X-Initiated-By", "")
    correlation_id = http_request.headers.get("X-Correlation-ID", "")

    task_id = request.params.id or request.params.message.messageId or str(uuid.uuid4())
    query = request.params.message.parts[0].get("text", "") if request.params.message.parts else ""
    logger.info(
        f"[PagerDuty Agent] Query: {query[:100]} | Task: {task_id}"
        + (f" | CorrelationID: {correlation_id}" if correlation_id else "")
        + (f" | InitiatedBy: {initiated_by}" if initiated_by else "")
        + (f" | OBO: {obo_token[:40]}..." if obo_token else "")
    )

    try:
        tool_plan = plan_tool_calls(query)
        tool_results = execute_tool_calls(tool_plan)
        response_text = synthesize_response(query, tool_results)
        logger.info(f"[PagerDuty Agent] Completed task: {task_id}")
        return JSONResponse({"jsonrpc": "2.0", "id": request.id, "result": {
            "kind": "message",
            "role": "agent",
            "messageId": str(uuid.uuid4()),
            "parts": [{"kind": "text", "text": response_text}]
        }})
    except Exception as e:
        logger.error(f"[PagerDuty Agent] Error: {str(e)[:200]}")
        return JSONResponse({"jsonrpc": "2.0", "id": request.id, "result": {
            "kind": "message",
            "role": "agent",
            "messageId": str(uuid.uuid4()),
            "parts": [{"kind": "text", "text": f"PagerDuty agent error: {str(e)[:300]}"}]
        }})


def plan_tool_calls(query: str) -> list:
    prompt = f"""Given this query about PagerDuty: "{query}"

Available tools:
- list_incidents: List incidents (params: status="triggered,acknowledged", limit=10, since_hours=24)
- get_incident: Get details for one incident (params: incident_id)
- list_oncall: Who is on-call right now (params: limit=5)
- list_services: List PagerDuty services (params: limit=20)
- list_escalation_policies: List escalation policies (params: limit=10)
- list_teams: List teams (params: limit=20)

Return ONLY a JSON array of tool calls. Example:
[{{"tool": "list_incidents", "params": {{"status": "triggered", "limit": 10}}}}]

Return ONLY the JSON array, nothing else."""

    text = call_gemini_with_fallback(prompt).strip()
    start = text.find('[')
    end = text.rfind(']') + 1
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end])
        except Exception:
            pass
    return [{"tool": "list_incidents", "params": {"status": "triggered,acknowledged", "limit": 10}}]


def execute_tool_calls(tool_plan: list) -> list:
    results = []
    for call in tool_plan[:3]:
        tool_name = call.get("tool")
        params = call.get("params", {})
        try:
            result = getattr(pd_tools, tool_name)(**params)
            results.append({"tool": tool_name, "result": result})
            logger.info(f"[PagerDuty Agent] Tool {tool_name} executed")
        except Exception as e:
            results.append({"tool": tool_name, "error": str(e)})
            logger.warning(f"[PagerDuty Agent] Tool {tool_name} failed: {e}")
    return results


def synthesize_response(query: str, tool_results: list) -> str:
    context = json.dumps(tool_results, indent=2, default=str)[:4000]
    prompt = f"""{SYSTEM_PROMPT}

Original query: "{query}"

PagerDuty data retrieved:
{context}

Write a clear, professional response using the data above.
Include IDs and timestamps where relevant. Use bullet points for lists."""

    return call_gemini_with_fallback(prompt)


@app.get("/.well-known/agent.json")
async def agent_metadata():
    return {
        "name": "PagerDuty Specialist Agent",
        "description": "A2A specialist agent for PagerDuty incident management",
        "version": "1.0.0",
        "skills": [
            {"id": "pagerduty-incident-management"},
            {"id": "pagerduty-service-team-ops"}
        ],
        "capabilities": {"streaming": False}
    }

@app.get("/.well-known/agent-card.json")
async def agent_card():
    """A2A 0.3.0 agent card — required by MuleSoft Agent Fabric broker for agent discovery."""
    return {
        "protocolVersion": "0.3.0",
        "name": "PagerDuty Specialist Agent",
        "description": "A2A specialist agent for PagerDuty incident management, on-call schedules, escalation policies, and alerts.",
        "url": "http://3.129.60.192:8080",
        "version": "1.0.0",
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "stateTransitionHistory": False
        },
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [
            {
                "id": "pagerduty-incident-management",
                "name": "PagerDuty Incident Management",
                "description": "Query active incidents, alerts, P1/P2/P3 status, on-call schedules, and escalation policies.",
                "tags": [],
                "inputModes": ["text/plain"],
                "outputModes": ["text/plain"]
            }
        ]
    }

@app.get("/health")
async def health():
    return {"status": "UP", "service": "muleops-pagerduty-agent", "version": "1.0.0"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))