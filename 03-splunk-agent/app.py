"""
Splunk Ops Specialist Agent — A2A FastAPI Application
Uses Google Gemini (same key as the broker) instead of AWS Bedrock.
No AWS account needed.
"""
import os
import json
import uuid
import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import google.generativeai as genai
from splunk_tools import SplunkTools
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

PRIMARY_KEY = os.environ.get("GEMINI_API_KEY")
FALLBACK_KEY = os.environ.get("GEMINI_API_KEY_FALLBACK")

def call_gemini_with_fallback(prompt: str) -> str:
    """Call Gemini with automatic fallback to second key on quota errors."""
    keys = [k for k in [PRIMARY_KEY, FALLBACK_KEY] if k]
    last_error = None
    for key in keys:
        try:
            genai.configure(api_key=key)
            m = genai.GenerativeModel("gemini-3.5-flash-lite")
            return m.generate_content(prompt).text
        except Exception as e:
            if "429" in str(e) or "quota" in str(e).lower():
                logger.warning(f"[Splunk Agent] Quota exceeded on key ...{key[-6:]} — trying fallback")
                last_error = e
                continue
            raise e
    raise last_error or Exception("All Gemini API keys exhausted")

app = FastAPI(title="MuleOps Splunk Ops Specialist Agent", version="1.0.0")
splunk = SplunkTools(
    host=os.environ.get("SPLUNK_HOST"),
    token=os.environ.get("SPLUNK_TOKEN"),
    port=int(os.environ.get("SPLUNK_PORT", 8089)),
    scheme=os.environ.get("SPLUNK_SCHEME", "https")
)

SYSTEM_PROMPT = """You are a Splunk operations specialist for a MuleSoft integration platform.
You search application logs, identify error patterns, and analyze operational data.
Include result counts, time ranges, and specific error messages in your responses.
Format log data clearly with bullet points."""


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
        f"[Splunk Agent] Query: {query[:100]} | Task: {task_id}"
        + (f" | CorrelationID: {correlation_id}" if correlation_id else "")
        + (f" | InitiatedBy: {initiated_by}" if initiated_by else "")
        + (f" | OBO: {obo_token[:40]}..." if obo_token else "")
    )

    try:
        spl = generate_spl(query)
        results = splunk.run_search(spl, max_results=50)
        response_text = synthesize_response(query, spl, results)
        return JSONResponse({"jsonrpc": "2.0", "id": request.id, "result": {
            "kind": "message",
            "role": "agent",
            "messageId": str(uuid.uuid4()),
            "parts": [{"kind": "text", "text": response_text}]
        }})
    except Exception as e:
        logger.error(f"[Splunk Agent] Error: {str(e)}")
        return JSONResponse({"jsonrpc": "2.0", "id": request.id, "result": {
            "kind": "message",
            "role": "agent",
            "messageId": str(uuid.uuid4()),
            "parts": [{"kind": "text", "text": f"Splunk agent error: {str(e)}"}]
        }})


def generate_spl(query: str) -> str:
    """Use Gemini to convert natural language to SPL."""
    prompt = f"""Convert this to a Splunk SPL query: "{query}"

Rules:
- Use index=mule_apps or index=muleops_ado as appropriate
- Default time range: last 1 hour unless specified
- Use | head 20 to limit results
- Return ONLY the SPL query, nothing else

Example: index=mule_apps level=ERROR | stats count by source | sort -count | head 10"""

    spl = call_gemini_with_fallback(prompt).strip()
    # Remove markdown code fences if present
    if spl.startswith("```"):
        lines = spl.split('\n')
        spl = '\n'.join(lines[1:-1] if lines[-1] == '```' else lines[1:])
    return spl


def synthesize_response(query: str, spl: str, results: dict) -> str:
    """Use Gemini to generate a natural language response from Splunk data."""
    context = json.dumps(results, indent=2, default=str)[:3000]
    prompt = f"""{SYSTEM_PROMPT}

Query: "{query}"
SPL used: {spl}
Results: {context}

Write a clear professional response. Include result counts, patterns, and relevant log details."""

    return call_gemini_with_fallback(prompt)


@app.get("/.well-known/agent.json")
async def agent_metadata():
    return {
        "name": "Splunk Ops Specialist Agent",
        "version": "1.0.0",
        "skills": [{"id": "splunk-log-search"}, {"id": "ado-alert-monitoring"}],
        "capabilities": {"streaming": False}
    }

@app.get("/.well-known/agent-card.json")
async def agent_card():
    """A2A 0.3.0 agent card — required by MuleSoft Agent Fabric broker for agent discovery."""
    return {
        "protocolVersion": "0.3.0",
        "name": "Splunk Ops Specialist Agent",
        "description": "A2A specialist agent for Splunk log search, error analysis, SPL query generation, and ADO alert monitoring.",
        "url": "http://3.129.60.192:8081",
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
                "id": "splunk-log-search",
                "name": "Splunk Log Search",
                "description": "Search application logs, generate SPL queries, analyze error patterns, and query observability data.",
                "tags": [],
                "inputModes": ["text/plain"],
                "outputModes": ["text/plain"]
            },
            {
                "id": "ado-alert-monitoring",
                "name": "ADO Alert Monitoring",
                "description": "Query ADO (Application Data Observability) alerts and saved searches from Splunk.",
                "tags": [],
                "inputModes": ["text/plain"],
                "outputModes": ["text/plain"]
            }
        ]
    }

@app.get("/health")
async def health():
    return {"status": "UP", "service": "muleops-splunk-agent", "version": "1.0.0"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))