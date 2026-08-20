"""
Integration System Agent — A2A FastAPI Wrapper for Salesforce Agentforce
Translates A2A protocol requests into Agentforce Agent API calls.
"""
import os
import json
import logging
from dotenv import load_dotenv
load_dotenv()  # Load .env BEFORE reading env vars

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from agentforce_client import AgentforceClient

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="MuleOps Integration System Agent", version="1.0.0")
sf_client = AgentforceClient(
    client_id=os.environ.get("SF_CLIENT_ID"),
    client_secret=os.environ.get("SF_CLIENT_SECRET"),
    instance_url=os.environ.get("SF_INSTANCE_URL"),
    agent_id=os.environ.get("SF_AGENT_ID"),
    api_base_url=os.environ.get("SF_AGENT_API_BASE_URL", "https://api.salesforce.com"),
    private_key_path=os.environ.get("SF_PRIVATE_KEY_PATH"),
    run_as_user=os.environ.get("SF_RUN_AS_USER"),
)

class A2AMessage(BaseModel):
    role: str
    parts: list

class A2AParams(BaseModel):
    id: str
    message: A2AMessage

class A2ARequest(BaseModel):
    jsonrpc: str = "2.0"
    method: str
    id: str
    params: A2AParams


@app.post("/a2a")
async def handle_a2a(http_request: Request, request: A2ARequest):
    # Extract OBO audit headers forwarded by the broker
    obo_token = http_request.headers.get("X-OBO-Token", "")
    initiated_by = http_request.headers.get("X-Initiated-By", "")
    correlation_id = http_request.headers.get("X-Correlation-ID", "")

    task_id = request.params.id
    query = request.params.message.parts[0].get("text", "") if request.params.message.parts else ""
    logger.info(
        f"[Integration Agent] Query: {query[:100]} | Task: {task_id}"
        + (f" | CorrelationID: {correlation_id}" if correlation_id else "")
        + (f" | InitiatedBy: {initiated_by}" if initiated_by else "")
        + (f" | OBO: {obo_token[:40]}..." if obo_token else "")
    )
    try:
        response_text = sf_client.send_message(query, initiated_by=initiated_by or None)
        logger.info(f"[Integration Agent] Completed task: {task_id}")
        return JSONResponse({"jsonrpc": "2.0", "id": request.id, "result": {
            "id": task_id, "status": {"state": "completed"},
            "artifacts": [{"parts": [{"text": response_text}]}]
        }})
    except Exception as e:
        logger.error(f"[Integration Agent] Error: {str(e)}")
        return JSONResponse({"jsonrpc": "2.0", "id": request.id, "result": {
            "id": task_id, "status": {"state": "failed"},
            "artifacts": [{"parts": [{"text": f"Integration agent error: {str(e)}"}]}]
        }})


@app.get("/.well-known/agent.json")
async def agent_metadata():
    return {
        "name": "Integration System Agent",
        "description": "A2A wrapper for Agentforce Service Agent — CloudHub application metadata queries",
        "version": "1.0.0",
        "skills": [{"id": "cloudhub-app-monitoring", "name": "CloudHub App Monitoring"}],
        "capabilities": {"streaming": False}
    }

@app.get("/.well-known/agent-card.json")
async def agent_card():
    """A2A 0.3.0 agent card — required by MuleSoft Agent Fabric broker for agent discovery."""
    return {
        "protocolVersion": "0.3.0",
        "name": "Integration System Agent",
        "description": "A2A wrapper for Salesforce Agentforce — CloudHub application metadata, vCore usage, runtime versions, Java compliance, static IPs, and business group queries.",
        "url": "http://3.129.60.192:8082",
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
                "id": "cloudhub-app-monitoring",
                "name": "CloudHub App Monitoring",
                "description": "Query CloudHub application metadata, vCore usage, runtime versions, Java compliance, static IPs, and business groups via Salesforce Agentforce.",
                "tags": [],
                "inputModes": ["text/plain"],
                "outputModes": ["text/plain"]
            }
        ]
    }

@app.get("/health")
async def health():
    return {"status": "UP", "service": "muleops-integration-agent", "version": "1.0.0"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
