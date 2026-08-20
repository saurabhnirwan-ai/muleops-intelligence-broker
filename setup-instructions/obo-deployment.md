# EC2 Deployment — OBO Token Update

Run these commands on EC2 (SSH into 3.137.192.48) to deploy the OBO changes.

---

## 1. Update PagerDuty Agent (port 8080)

```bash
cat > /opt/pagerduty-agent/app.py << 'PYEOF'
"""
PagerDuty Specialist Agent — A2A FastAPI Application
Uses Google Gemini with automatic key rotation (primary → fallback on quota error).
"""
import os
import json
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

class A2AParams(BaseModel):
    id: str
    message: A2AMessage

class A2ARequest(BaseModel):
    jsonrpc: str = "2.0"
    method: str
    id: str
    params: A2AParams


def get_gemini_model(api_key: str):
    genai.configure(api_key=api_key)
    return genai.GenerativeModel("gemini-2.5-flash")


def call_gemini_with_fallback(prompt: str) -> str:
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


@app.post("/a2a")
async def handle_a2a(http_request: Request, request: A2ARequest):
    obo_token = http_request.headers.get("X-OBO-Token", "")
    initiated_by = http_request.headers.get("X-Initiated-By", "")
    correlation_id = http_request.headers.get("X-Correlation-ID", "")

    task_id = request.params.id
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
            "id": task_id, "status": {"state": "completed"},
            "artifacts": [{"parts": [{"text": response_text}]}]
        }})
    except Exception as e:
        logger.error(f"[PagerDuty Agent] Error: {str(e)[:200]}")
        return JSONResponse({"jsonrpc": "2.0", "id": request.id, "result": {
            "id": task_id, "status": {"state": "failed"},
            "artifacts": [{"parts": [{"text": f"PagerDuty agent error: {str(e)[:300]}"}]}]
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

@app.get("/health")
async def health():
    return {"status": "UP", "service": "muleops-pagerduty-agent", "version": "1.0.0"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
PYEOF
echo "PagerDuty app.py written"

# Restart
fuser -k 8080/tcp 2>/dev/null || true
sleep 1
cd /opt/pagerduty-agent
nohup python3 app.py > ~/pagerduty-agent.log 2>&1 &
sleep 3
curl -s http://localhost:8080/health
```

---

## 2. Update Splunk Agent (port 8081)

> **Note:** First find the correct directory name for the Splunk agent:
> ```bash
> ls /opt/
> ```
> Then replace `/opt/splunk-agent` below with the actual path if different.

```bash
cat > /opt/splunk-agent/app.py << 'PYEOF'
"""
Splunk Ops Specialist Agent — A2A FastAPI Application
Uses Google Gemini (same key as the broker) instead of AWS Bedrock.
"""
import os
import json
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
    keys = [k for k in [PRIMARY_KEY, FALLBACK_KEY] if k]
    last_error = None
    for key in keys:
        try:
            genai.configure(api_key=key)
            m = genai.GenerativeModel("gemini-2.5-flash")
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
    obo_token = http_request.headers.get("X-OBO-Token", "")
    initiated_by = http_request.headers.get("X-Initiated-By", "")
    correlation_id = http_request.headers.get("X-Correlation-ID", "")

    task_id = request.params.id
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
            "id": task_id, "status": {"state": "completed"},
            "artifacts": [{"parts": [{"text": response_text}]}]
        }})
    except Exception as e:
        logger.error(f"[Splunk Agent] Error: {str(e)}")
        return JSONResponse({"jsonrpc": "2.0", "id": request.id, "result": {
            "id": task_id, "status": {"state": "failed"},
            "artifacts": [{"parts": [{"text": f"Splunk agent error: {str(e)}"}]}]
        }})


def generate_spl(query: str) -> str:
    prompt = f"""Convert this to a Splunk SPL query: "{query}"

Rules:
- Use index=mule_apps or index=muleops_ado as appropriate
- Default time range: last 1 hour unless specified
- Use | head 20 to limit results
- Return ONLY the SPL query, nothing else

Example: index=mule_apps level=ERROR | stats count by source | sort -count | head 10"""

    spl = call_gemini_with_fallback(prompt).strip()
    if spl.startswith("```"):
        lines = spl.split('\n')
        spl = '\n'.join(lines[1:-1] if lines[-1] == '```' else lines[1:])
    return spl


def synthesize_response(query: str, spl: str, results: dict) -> str:
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

@app.get("/health")
async def health():
    return {"status": "UP", "service": "muleops-splunk-agent", "version": "1.0.0"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
PYEOF
echo "Splunk app.py written"

# Restart
fuser -k 8081/tcp 2>/dev/null || true
sleep 1
cd /opt/splunk-agent
nohup python3 app.py > ~/splunk-agent.log 2>&1 &
sleep 3
curl -s http://localhost:8081/health
```

---

## 3. Update Integration Agent (port 8082)

```bash
cat > /opt/integration-agent/app.py << 'PYEOF'
"""
Integration System Agent — A2A FastAPI Wrapper for Salesforce Agentforce
Translates A2A protocol requests into Agentforce Agent API calls.
"""
import os
import logging
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
    api_base_url=os.environ.get("SF_AGENT_API_BASE_URL", "https://api.salesforce.com")
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
        response_text = sf_client.send_message(query)
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

@app.get("/health")
async def health():
    return {"status": "UP", "service": "muleops-integration-agent", "version": "1.0.0"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8082)))
PYEOF
echo "Integration app.py written"

# Also write clean agentforce_client.py (full verified version)
cat > /opt/integration-agent/agentforce_client.py << 'PYEOF'
"""
Salesforce Agentforce Client
Handles OAuth token acquisition and Agent API session management.
"""
import requests
import logging
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

class AgentforceClient:
    def __init__(self, client_id: str, client_secret: str, instance_url: str, agent_id: str, api_base_url: str = "https://api.salesforce.com"):
        if not all([client_id, client_secret, instance_url, agent_id]):
            raise ValueError("SF_CLIENT_ID, SF_CLIENT_SECRET, SF_INSTANCE_URL, SF_AGENT_ID are required")
        self.client_id = client_id
        self.client_secret = client_secret
        self.instance_url = instance_url.rstrip("/")
        self.agent_id = agent_id
        self.api_base_url = api_base_url.rstrip("/")
        self._access_token: Optional[str] = None
        self._session_id: Optional[str] = None

    def _get_token(self) -> str:
        r = requests.post(
            f"{self.instance_url}/services/oauth2/token",
            data={"grant_type": "client_credentials",
                  "client_id": self.client_id,
                  "client_secret": self.client_secret},
            timeout=15
        )
        r.raise_for_status()
        self._access_token = r.json()["access_token"]
        logger.info("[Agentforce] Access token acquired")
        return self._access_token

    def _create_session(self) -> str:
        token = self._access_token or self._get_token()
        r = requests.post(
            f"{self.api_base_url}/einstein/ai-agent/v1/agents/{self.agent_id}/sessions",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"externalSessionKey": str(uuid.uuid4()), "bypassUser": True},
            timeout=15
        )
        if r.status_code == 401:
            token = self._get_token()
            r = requests.post(
                f"{self.api_base_url}/einstein/ai-agent/v1/agents/{self.agent_id}/sessions",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"externalSessionKey": str(uuid.uuid4()), "bypassUser": True},
                timeout=15
            )
        r.raise_for_status()
        self._session_id = r.json()["sessionId"]
        logger.info(f"[Agentforce] Session created: {self._session_id}")
        return self._session_id

    def send_message(self, message: str) -> str:
        """Send a message to the Agentforce agent and return the text response."""
        token = self._access_token or self._get_token()
        session_id = self._session_id or self._create_session()
        r = requests.post(
            f"{self.api_base_url}/einstein/ai-agent/v1/agents/{self.agent_id}/sessions/{session_id}/messages",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"message": {"role": "user", "content": [{"type": "text", "text": message}]},
                  "sequenceId": 1},
            timeout=60
        )
        if r.status_code in (401, 404):
            token = self._get_token()
            session_id = self._create_session()
            r = requests.post(
                f"{self.api_base_url}/einstein/ai-agent/v1/agents/{self.agent_id}/sessions/{session_id}/messages",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"message": {"role": "user", "content": [{"type": "text", "text": message}]},
                      "sequenceId": 1},
                timeout=60
            )
        r.raise_for_status()
        data = r.json()
        messages = data.get("messages", [])
        for msg in messages:
            if msg.get("role") == "agent":
                for part in msg.get("content", []):
                    if part.get("type") == "text":
                        return part["text"]
        return "No response received from Agentforce agent"
PYEOF
echo "agentforce_client.py written"

# Restart integration agent
fuser -k 8082/tcp 2>/dev/null || true
sleep 1
cd /opt/integration-agent
nohup python3 app.py > ~/integration-agent.log 2>&1 &
sleep 3
curl -s http://localhost:8082/health
```

---

## 4. Verify All Three Agents Are Running

```bash
curl -s http://localhost:8080/health && echo ""
curl -s http://localhost:8081/health && echo ""
curl -s http://localhost:8082/health && echo ""
```

Expected output:
```
{"status":"UP","service":"muleops-pagerduty-agent","version":"1.0.0"}
{"status":"UP","service":"muleops-splunk-agent","version":"1.0.0"}
{"status":"UP","service":"muleops-integration-agent","version":"1.0.0"}
```

---

## 5. Test OBO Token Logging

```bash
# Send a test A2A request with mock OBO headers to PagerDuty agent
curl -s -X POST http://localhost:8080/a2a \
  -H "Content-Type: application/json" \
  -H "X-OBO-Token: eyJzbGFja191c2VyX2lkIjoidGVzdCJ9" \
  -H "X-Initiated-By: U_TEST_USER" \
  -H "X-Correlation-ID: test-obo-001" \
  -d '{"jsonrpc":"2.0","method":"tasks/send","id":"test-obo-001","params":{"id":"task-001","message":{"role":"user","parts":[{"text":"what are the active incidents?"}]}}}' \
  | python3 -m json.tool

# Confirm OBO headers appear in logs
tail -20 ~/pagerduty-agent.log | grep -E "OBO|InitiatedBy|CorrelationID"
```
