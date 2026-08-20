# MuleOps Intelligence Broker

> Multi-agent AI platform built on **MuleSoft Anypoint Agent Network** — routes natural language operations queries to PagerDuty, Splunk, and Salesforce Agentforce via the A2A v0.3.0 protocol, orchestrated by **Gemini 3.5 Flash Lite** and enforced by **Flex Gateway**.

---

## Architecture

```
                          Slack
                            │
                     demo-broker (Relay)
                            │  A2A JSON-RPC
                     ┌──────▼──────────────────────────────────┐
                     │   MuleSoft Agent Network (CloudHub 2.0)  │
                     │                                          │
                     │   Gemini 3.5 Flash Lite (LLM broker)     │
                     │           ┌──────────────┐               │
                     │           │ Flex Gateway  │ (ingress +    │
                     │           │  + policies  │  OBO/JWT/ABAC)│
                     │           └──────┬───────┘               │
                     └──────────────────┼───────────────────────┘
                                        │ A2A v0.3.0
                    ┌───────────────────┼──────────────────┐
                    │                   │                  │
             ┌──────▼──────┐   ┌────────▼──────┐  ┌───────▼──────────────┐
             │  PagerDuty  │   │  Splunk Ops   │  │ Integration System   │
             │   Agent     │   │    Agent      │  │  Agent (Agentforce)  │
             │  :8080      │   │   :8081       │  │  :8082               │
             └─────────────┘   └───────────────┘  └──────────────────────┘
                                        │
                               ┌────────▼────────┐
                               │ Governance MCP   │
                               │ Server (Mule)    │
                               └─────────────────┘
```

---

## Components

| Directory | What it is |
|---|---|
| `01-mulesoft/agent-network/` | MuleSoft Agent Network definition (`agent-network.yaml`) — broker, LLM, agents, MCP, connections |
| `01-mulesoft/agent-fabric-config/` | Flex Gateway policies (rate limiting, JWT, ABAC, client-ID enforcement, PII detection) |
| `01-mulesoft/governance-mcp-server/` | Mule 4 MCP server — compliance checks + ADO log writes to Splunk |
| `02-pagerduty-agent/` | FastAPI A2A agent — PagerDuty incidents, on-call schedules, escalation policies |
| `03-splunk-agent/` | FastAPI A2A agent — Splunk log search, SPL generation, ADO alert queries |
| `04-integration-system-agent/` | FastAPI A2A wrapper for Salesforce Agentforce — CloudHub app metadata |
| `demo-broker/` | Slack relay → MuleSoft Agent Network broker (Flex Gateway) |
| `docs/` | Deployment guides, wiring docs |
| `setup-instructions/` | Flex Gateway, OBO token, Slack app setup |

---

## Tech Stack

- **Orchestration**: MuleSoft Anypoint Agent Network (Agent Fabric) on CloudHub 2.0
- **LLM**: Google Gemini 3.5 Flash Lite (via `generativelanguage.googleapis.com`)
- **Protocol**: A2A v0.3.0 (Agent-to-Agent JSON-RPC)
- **Gateway**: MuleSoft Flex Gateway (ingress, JWT validation, ABAC, rate limiting, PII detection)
- **MCP**: MuleSoft MCP Connector (Streamable HTTP transport)
- **Agents**: FastAPI (Python) + `google-generativeai` SDK
- **Slack**: Slack Events API + Bot OAuth
- **Infra**: AWS EC2 (t3.small, us-east-2), CloudHub 2.0

---

## Prerequisites

- Anypoint Platform account with Agent Network enabled
- Google AI Studio API key (for `gemini-3.5-flash-lite`)
- PagerDuty API token
- Splunk Cloud instance with HEC enabled
- Salesforce org with Agentforce agent deployed
- Slack app with Events API and `chat:write` scope
- AWS EC2 instance (or equivalent) for Python agents
- `anypoint-cli-v4` installed locally

---

## Environment Variables

### `02-pagerduty-agent/.env`
```
GEMINI_API_KEY=your_gemini_api_key
GEMINI_API_KEY_FALLBACK=your_fallback_key   # optional
PAGERDUTY_API_TOKEN=your_pagerduty_token
PORT=8080
```

### `03-splunk-agent/.env`
```
GEMINI_API_KEY=your_gemini_api_key
GEMINI_API_KEY_FALLBACK=your_fallback_key   # optional
SPLUNK_HOST=your-splunk.splunkcloud.com
SPLUNK_TOKEN=your_splunk_hec_token
SPLUNK_PORT=8089
SPLUNK_SCHEME=https
PORT=8081
```

### `04-integration-system-agent/.env`
```
SF_CLIENT_ID=your_sf_connected_app_client_id
SF_CLIENT_SECRET=your_sf_client_secret
SF_INSTANCE_URL=https://your-org.my.salesforce.com
SF_AGENT_ID=your_agentforce_agent_id
SF_AGENT_API_BASE_URL=https://api.salesforce.com
SF_PRIVATE_KEY_PATH=/path/to/private.key
SF_RUN_AS_USER=your_sf_username
PORT=8082
```

### `demo-broker/.env`
```
SLACK_BOT_TOKEN=xoxb-your-slack-bot-token
MULE_BROKER_URL=https://your-flex-gateway-url/muleops_intelligence_broker
PORT=9000
```

### `01-mulesoft/governance-mcp-server` (CloudHub properties)
```
splunk.hec.host=your-splunk.splunkcloud.com
splunk.hec.port=8088
splunk.hec.token=your_splunk_hec_token
anypoint.org.id=your_anypoint_org_id
anypoint.client.id=your_connected_app_client_id
anypoint.client.secret=your_connected_app_client_secret
```

### `01-mulesoft/agent-network/agent-network.yaml`
```
GEMINI_API_KEY=your_gemini_api_key   # used in gemini-flash-connection
```

---

## Deployment

### 1. Deploy Python Agents to EC2

```bash
# Copy files to EC2
scp -i ~/.ssh/your-key.pem 02-pagerduty-agent/app.py ec2-user@<EC2_IP>:/opt/pagerduty-agent/
scp -i ~/.ssh/your-key.pem 03-splunk-agent/app.py    ec2-user@<EC2_IP>:/opt/splunk-agent/
scp -i ~/.ssh/your-key.pem 04-integration-system-agent/app.py ec2-user@<EC2_IP>:/opt/integration-agent/

# Restart agents
ssh -i ~/.ssh/your-key.pem ec2-user@<EC2_IP> \
  "fuser -k 8080/tcp 2>/dev/null; cd /opt/pagerduty-agent && nohup python3 app.py > ~/pagerduty-agent.log 2>&1 &"
```

See `docs/EC2-DEPLOYMENT-GUIDE.md` for full details.

### 2. Publish & Deploy Agent Network

```bash
cd 01-mulesoft/agent-network
anypoint-cli-v4 agent-network:publish
anypoint-cli-v4 agent-network:deploy
```

### 3. Deploy Governance MCP Server

```bash
cd 01-mulesoft/governance-mcp-server
mvn deploy -DmuleDeploy
```

### 4. Deploy Slack Relay (demo-broker)

```bash
cd demo-broker
docker build -t muleops-demo-broker .
# Deploy to AWS App Runner, EC2, or any container host
```

---

## A2A Protocol Notes

The Python agents implement A2A v0.3.0 `message/send`:

- **Endpoint**: `POST /` (root — per A2A spec, the `url` in agent card IS the A2A endpoint)
- **Request**: `{"jsonrpc":"2.0","method":"message/send","params":{"message":{...}}}`
- **Response**: `{"result":{"kind":"message","role":"agent","messageId":"...","parts":[{"kind":"text","text":"..."}]}}`

---

## Slack Usage

Mention the bot in any channel where it's invited:

```
@MuleOps Intelligence Broker what are the active P1 incidents?
@MuleOps Intelligence Broker search Splunk for timeout errors in the last hour
@MuleOps Intelligence Broker who is on-call right now?
@MuleOps Intelligence Broker how many apps in BT-INTEGRATION are not on Java 17?
@MuleOps Intelligence Broker check compliance for the payment-processing app
```

---

## Demo Runner

Run all 8 demo queries against the live broker:

```bash
node 01-mulesoft/agent-network/run_demo.js
```

Results are written to `demo_results.txt`.

---

## License

MIT