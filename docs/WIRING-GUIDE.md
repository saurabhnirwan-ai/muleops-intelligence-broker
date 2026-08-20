# MuleOps Intelligence Broker — Master Wiring Guide

## Overview

The MuleOps Intelligence Broker is a multi-agent orchestration system built on MuleSoft Agent Fabric. It routes natural-language operational queries from Slack to the appropriate domain-specialist agent, consolidates responses, and returns a professionally formatted answer — all within a single conversation thread.

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            USER INTERFACE LAYER                             │
│                                                                             │
│   [Slack Workspace]  ──────────────────────────────────────────────────►   │
│   "What alerts are active in BT-INTEGRATION?"                               │
└─────────────────────────────┬───────────────────────────────────────────────┘
                              │ HTTPS POST
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       MULESOFT AGENT FABRIC LAYER                           │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │              BROKER MULE APPLICATION (CloudHub 2.0)                  │   │
│  │                                                                      │   │
│  │  HTTP Listener → AI Agent Component (Gemini Flash)                   │   │
│  │                      │                                               │   │
│  │            ┌──────────┼───────────────┐                              │   │
│  │            ↓          ↓               ↓                              │   │
│  │  [Route: PagerDuty] [Route: Splunk] [Route: CloudHub]                │   │
│  │            │          │               │                              │   │
│  │        A2A Call   A2A Call        A2A Call                           │   │
│  └────────────┼──────────┼───────────────┼──────────────────────────────┘   │
│               │          │               │                                   │
└───────────────┼──────────┼───────────────┼───────────────────────────────────┘
                │          │               │  (via Flex Gateway — provider instances)
                ▼          ▼               ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                        SPECIALIST AGENT LAYER                                │
│                                                                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────────────────┐     │
│  │  PagerDuty      │  │  Splunk Ops     │  │  Integration System      │     │
│  │  Specialist     │  │  Specialist     │  │  Agent (Agentforce)      │     │
│  │  Agent          │  │  Agent          │  │                          │     │
│  │                 │  │                 │  │  Salesforce Agentforce   │     │
│  │  Python/FastAPI │  │  Python/FastAPI │  │  + FastAPI A2A Wrapper   │     │
│  │  AWS App Runner │  │  AWS App Runner │  │  Heroku                  │     │
│  │  Claude Sonnet  │  │  Claude Sonnet  │  │  Native Agentforce LLM  │     │
│  │  (Bedrock)      │  │  (Bedrock)      │  │                          │     │
│  └────────┬────────┘  └────────┬────────┘  └───────────┬──────────────┘     │
│           │                   │                        │                    │
└───────────┼───────────────────┼────────────────────────┼────────────────────┘
            │                   │                        │
            ▼                   ▼                        ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                         BACKEND SYSTEMS LAYER                                │
│                                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐   │
│  │  PagerDuty   │  │  Splunk      │  │  Salesforce  │  │  Mule App      │   │
│  │  API +       │  │  API +       │  │  Data Cloud  │  │  Governance    │   │
│  │  MCP Server  │  │  MCP Server  │  │  (CloudHub   │  │  MCP Server    │   │
│  │              │  │              │  │   metadata)  │  │  (CloudHub)    │   │
│  └──────────────┘  └──────────────┘  └──────────────┘  └────────────────┘   │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Component Inventory

| # | Component | Type | Platform | URL/Endpoint |
|---|---|---|---|---|
| 1 | Broker Mule Application | Mule App | CloudHub 2.0 | `https://${broker.cloudhub.url}/api/broker` |
| 2 | Mule App Governance MCP Server | Mule App | CloudHub 2.0 | `https://${governance-mcp.cloudhub.url}/mcp` |
| 3 | PagerDuty Specialist Agent | Python FastAPI | AWS App Runner | `https://${pagerduty-agent.apprunner.url}` |
| 4 | Splunk Ops Specialist Agent | Python FastAPI | AWS App Runner | `https://${splunk-agent.apprunner.url}` |
| 5 | Integration System Agent | Python FastAPI + Agentforce | Heroku | `https://${integration-agent.heroku.url}` |
| 6 | Flex Gateway | MuleSoft | Self-managed / CloudHub | `https://${flex-gateway.url}` |
| 7 | Slack App | Slack | Slack Platform | Webhook to broker endpoint |

---

## Network Definition: Agent Fabric Skills

The broker's LLM (Gemini Flash) routes queries based on these 5 skill domains:

| Skill Domain | Routes To | Keywords / Intent |
|---|---|---|
| `pagerduty-incident-management` | PagerDuty Specialist | alerts, incidents, on-call, escalation, ack, resolve |
| `pagerduty-service-team-ops` | PagerDuty Specialist | services, teams, schedules, policies |
| `splunk-log-search` | Splunk Ops Specialist | logs, errors, search, SPL, exceptions, traces |
| `ado-alert-monitoring` | Splunk Ops Specialist | ADO alerts, saved searches, Splunk alerts |
| `cloudhub-app-monitoring` | Integration System Agent | vCores, apps, business groups, runtime, Java, static IP |

---

## Credential & Environment Variable Cross-Reference

Fill in this table before deployment. Use it as a master reference across all components.

### Broker Mule Application (`01-mulesoft/broker-mule-app/src/main/resources/config.yaml`)

| Property | Description | Where to Get |
|---|---|---|
| `gemini.api.key` | Gemini API key for broker LLM | Google AI Studio |
| `anypoint.client.id` | Connected App Client ID | Anypoint Platform → Access Management |
| `anypoint.client.secret` | Connected App Client Secret | Anypoint Platform → Access Management |
| `pagerduty.agent.url` | PagerDuty agent A2A endpoint (via Flex GW) | After deploying `02-pagerduty-agent/` |
| `splunk.agent.url` | Splunk agent A2A endpoint (via Flex GW) | After deploying `03-splunk-agent/` |
| `integration.agent.url` | Integration system agent A2A endpoint | After deploying `04-integration-system-agent/` |

### PagerDuty Agent (`02-pagerduty-agent/.env`)

| Variable | Description |
|---|---|
| `PAGERDUTY_API_TOKEN` | PagerDuty REST API token (read-only) |
| `PAGERDUTY_SERVICE_ID` | Default PagerDuty service ID for scoping |
| `PAGERDUTY_ESCALATION_POLICY_ID` | Default escalation policy ID |
| `PAGERDUTY_FROM_EMAIL` | Email address used in API request headers |
| `GEMINI_API_KEY` | Gemini API key (primary LLM). Get from https://aistudio.google.com/ |
| `GEMINI_API_KEY_FALLBACK` | Optional second Gemini key — used automatically on 429/quota errors |
| `PORT` | Port the agent listens on (default: `8080`) |

### Splunk Agent (`03-splunk-agent/.env`)

| Variable | Description |
|---|---|
| `SPLUNK_HOST` | Splunk instance hostname |
| `SPLUNK_TOKEN` | Splunk REST API token |
| `SPLUNK_PORT` | Default: `8089` |
| `SPLUNK_SCHEME` | Default: `https` |
| `GEMINI_API_KEY` | Gemini API key (primary LLM). Get from https://aistudio.google.com/ |
| `GEMINI_API_KEY_FALLBACK` | Optional second Gemini key — used automatically on 429/quota errors |
| `PORT` | Port the agent listens on (default: `8080`) |

### Integration System Agent (`04-integration-system-agent/.env`)

| Variable | Description |
|---|---|
| `SF_CLIENT_ID` | Salesforce Connected App Client ID |
| `SF_CLIENT_SECRET` | Salesforce Connected App Client Secret (used for Client Credentials fallback) |
| `SF_INSTANCE_URL` | Salesforce My Domain URL (e.g. `https://orgname.my.salesforce.com`) |
| `SF_AGENT_ID` | Agentforce Agent ID (starts with `0Xx`) |
| `SF_AGENT_API_BASE_URL` | Agent API base URL, usually `https://api.salesforce.com` |
| `SF_PRIVATE_KEY_PATH` | **JWT Bearer (preferred)** — path to RSA private key PEM file. Upload matching public cert to Connected App. |
| `SF_RUN_AS_USER` | **JWT Bearer (preferred)** — Salesforce username/email to impersonate. Must be pre-authorized in Connected App profiles. |
| `PORT` | Port the agent listens on (default: `8082`) |

### Mule App Governance MCP Server (`01-mulesoft/governance-mcp-server/src/main/resources/config.yaml`)

| Property | Description |
|---|---|
| `splunk.hec.url` | Splunk HEC endpoint for ADO log writing |
| `splunk.hec.token` | Splunk HEC token |
| `anypoint.org.id` | Anypoint Platform Organization ID |
| `anypoint.client.id` | Connected App Client ID |
| `anypoint.client.secret` | Connected App Client Secret |

---

## Deployment Order (Critical — Follow This Sequence)

```
Step 1:  Deploy Mule App Governance MCP Server (01-mulesoft/governance-mcp-server/)
         → Note the CloudHub URL

Step 2:  Deploy PagerDuty Specialist Agent (02-pagerduty-agent/)
         → Note the App Runner URL
         → Register behind Flex Gateway (05-flex-gateway/)
         → Note the Flex Gateway provider URL

Step 3:  Deploy Splunk Ops Specialist Agent (03-splunk-agent/)
         → Note the App Runner URL
         → Register behind Flex Gateway
         → Note the Flex Gateway provider URL

Step 4:  Deploy Integration System Agent (04-integration-system-agent/)
         → Note the Heroku URL
         → Register behind Flex Gateway
         → Note the Flex Gateway provider URL

Step 5:  Update Broker config with all agent URLs from Steps 2-4
         (01-mulesoft/broker-mule-app/src/main/resources/config.yaml)

Step 6:  Publish Agent Network to Anypoint Exchange
         (01-mulesoft/agent-network/agent-network.yaml)

Step 7:  Deploy Broker Mule Application (01-mulesoft/broker-mule-app/)
         → Note the CloudHub URL

Step 8:  Configure Slack App (06-slack-integration/)
         → Wire Slack webhook to broker CloudHub URL

Step 9:  Run end-to-end tests (07-testing/)
```

---

## OBO Token: End-to-End User Identity Propagation

The **OBO (On-Behalf-Of) token** carries the identity of the human who originated a request through the entire agent call chain. This creates a full audit trail from Slack → Broker → Specialist Agent → Backend system.

### How It Works

```
[Slack User] sends query in Slack channel
        │
        ▼
[Demo Broker / Mule Broker]
  build_obo_token(slack_user_id, channel)
  → base64( {"slack_user_id": "U123456", "channel": "C789", "initiated_at": "...", "source": "slack"} )
        │
        │  Forwards 3 audit headers on every A2A call:
        │    X-OBO-Token:      <base64-encoded identity payload>
        │    X-Initiated-By:   <slack_user_id>
        │    X-Correlation-ID: <uuid per request>
        ▼
[PagerDuty / Splunk Agent]
  Extracts and logs all 3 headers for audit
        │
[Integration System Agent]
  Extracts initiated_by from X-Initiated-By
  Passes it to AgentforceClient.send_message(query, initiated_by=initiated_by)
        │
        ▼
[Agentforce Session]
  externalSessionKey = "slack-<user_id>-<uuid>"
  → Salesforce audit logs now show the originating Slack user
```

### OBO Token Payload (decoded)

```json
{
  "slack_user_id": "U0123456789",
  "channel": "C0987654321",
  "initiated_at": "2026-11-08T07:10:00Z",
  "source": "slack"
}
```

### What Each Agent Does with OBO

| Agent | OBO Handling |
|---|---|
| PagerDuty Specialist | Logs `X-OBO-Token`, `X-Initiated-By`, `X-Correlation-ID` for audit |
| Splunk Ops Specialist | Logs `X-OBO-Token`, `X-Initiated-By`, `X-Correlation-ID` for audit |
| Integration System Agent | Logs all 3 headers **and** threads `initiated_by` into Agentforce `externalSessionKey` for end-to-end traceability in Salesforce |

---

## A2A Protocol: How the Broker Calls Agents

All specialist agents implement the **Agent-to-Agent (A2A) protocol**. The broker sends OBO audit headers alongside every A2A request:

```json
POST https://<agent-flex-gw-url>/a2a
Content-Type: application/json
Authorization: Bearer <client-credential-injected-by-agent-fabric>
X-OBO-Token: eyJzbGFja191c2VyX2lkIjoiVTAxMjM0NTYiLCAic291cmNlIjoic2xhY2sifQ==
X-Initiated-By: U0123456
X-Correlation-ID: 7f3a1b2c-4d5e-6f7a-8b9c-0d1e2f3a4b5c

{
  "jsonrpc": "2.0",
  "method": "tasks/send",
  "id": "req-001",
  "params": {
    "id": "task-uuid",
    "message": {
      "role": "user",
      "parts": [{ "text": "What are the active P1 incidents?" }]
    }
  }
}
```

The agent responds:

```json
{
  "jsonrpc": "2.0",
  "id": "req-001",
  "result": {
    "id": "task-uuid",
    "status": { "state": "completed" },
    "artifacts": [{
      "parts": [{ "text": "There are 2 active P1 incidents: ..." }]
    }]
  }
}
```

---

## Delegated Agent Egress Pattern

For each specialist agent, Flex Gateway creates **two instances**:

```
[Broker] ──► [Consumer Instance (Sub-Agent Proxy)]
                         │ injects client credentials automatically
                         ▼
             [Provider Instance (Flex Gateway)]
                         │ enforces client-ID, JWT, rate limit
                         ▼
             [Agent Runtime: App Runner / Heroku]
```

- **Provider instance**: Hard security perimeter. You apply policies here.
- **Consumer instance**: Auto-created by Agent Fabric when you deploy the network. Broker uses this — never holds secrets.

---

## Flex Gateway Policy Stack (Applied Per Agent)

| Policy | Layer | Purpose |
|---|---|---|
| Client-ID Enforcement | Inbound (Provider) | Only known clients can call the agent |
| JWT Validation | Inbound (Provider) | Validate Agent Fabric-issued tokens |
| Rate Limiting | Inbound (Provider) | Prevent LLM loops from burning API credits |
| IP Allowlist | Inbound (Provider) | Restrict to known Flex GW/CloudHub IPs |
| Wallarm Advanced Threat | Inbound (Provider) | OWASP protection |
| ABAC (Attribute-Based AC) | Inbound (Provider) | Role-based agent access |
| MCP PII Detector | MCP tools only | Mask PII in MCP tool responses |
| HTTP Caching | Response | Cache repeated identical queries |

---

## Quick Test: End-to-End Validation

Once everything is deployed, test with these 3 queries via Postman or Slack:

```bash
# Query 1: PagerDuty routing
curl -X POST https://<broker-url>/api/broker \
  -H "Content-Type: application/json" \
  -d '{"query": "What are the active P1 incidents right now?"}'

# Query 2: Splunk routing
curl -X POST https://<broker-url>/api/broker \
  -H "Content-Type: application/json" \
  -d '{"query": "Search Splunk for ERROR logs in the last hour for mule-app-gateway"}'

# Query 3: CloudHub routing
curl -X POST https://<broker-url>/api/broker \
  -H "Content-Type: application/json" \
  -d '{"query": "How many apps in BT-INTEGRATION are not running Java 17?"}'
```

Expected: Each query routes to the correct specialist, returns a real response, within 5–15 seconds.

---

## Support & Reference

- MuleSoft Agent Fabric docs: https://docs.mulesoft.com/general/
- A2A Protocol spec: https://google.github.io/A2A/
- Flex Gateway policies: https://docs.mulesoft.com/gateway/latest/
- Anypoint MCP Bridge: https://docs.mulesoft.com/general/
