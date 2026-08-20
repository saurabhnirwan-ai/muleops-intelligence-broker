# MuleSoft Deployment Guide

## Prerequisites

- Anypoint Platform account with CloudHub 2.0 access
- Maven 3.8+ installed locally
- Java 17 (JDK)
- Anypoint CLI v4 installed: `npm install -g anypoint-cli-v4`
- Connected App created in Anypoint → Access Management with scopes:
  - `CloudHub Application` (Read, Write)
  - `Exchange` (Contributor)
  - `Agent Network` (Read, Write)
  - `API Manager` (Read, Write)

---

## Step 1: Configure Credentials

### 1.1 Broker Application Config

Edit `broker-mule-app/src/main/resources/config.yaml`:

```yaml
gemini:
  api:
    key: "${GEMINI_API_KEY}"

anypoint:
  client:
    id: "<YOUR_CONNECTED_APP_CLIENT_ID>"
    secret: "<YOUR_CONNECTED_APP_CLIENT_SECRET>"

pagerduty:
  agent:
    url: "<FLEX_GW_PROVIDER_URL_FOR_PAGERDUTY_AGENT>"

splunk:
  agent:
    url: "<FLEX_GW_PROVIDER_URL_FOR_SPLUNK_AGENT>"

integration:
  agent:
    url: "<FLEX_GW_PROVIDER_URL_FOR_INTEGRATION_AGENT>"
```

### 1.2 Governance MCP Server Config

Edit `governance-mcp-server/src/main/resources/config.yaml`:

```yaml
splunk:
  hec:
    url: "https://<YOUR_SPLUNK_HOST>:8088/services/collector"
    token: "<YOUR_SPLUNK_HEC_TOKEN>"

anypoint:
  org:
    id: "<YOUR_ANYPOINT_ORG_ID>"
  client:
    id: "<YOUR_CONNECTED_APP_CLIENT_ID>"
    secret: "<YOUR_CONNECTED_APP_CLIENT_SECRET>"
```

---

## Step 2: Deploy Mule App Governance MCP Server

```bash
cd DF/01-mulesoft/governance-mcp-server

mvn clean deploy -DmuleDeploy \
  -Danypoint.username=<YOUR_ANYPOINT_USERNAME> \
  -Danypoint.password=<YOUR_ANYPOINT_PASSWORD> \
  -Dcloudhub.environment=Sandbox \
  -Dcloudhub.businessGroup=<YOUR_BG_NAME> \
  -Dcloudhub.region=us-east-1 \
  -Dcloudhub.workerType=MICRO \
  -Dcloudhub.workers=1
```

**After deployment:**
- Note the CloudHub URL: `https://muleops-governance-mcp-<random>.cloudhub.io`
- Test the health endpoint: `GET https://<url>/api/health`
- Register as MCP Server in Anypoint Exchange (see Step 5)

---

## Step 3: Deploy Broker Mule Application

> ⚠️ Do this AFTER all specialist agents are deployed and you have their Flex GW URLs.

```bash
cd DF/01-mulesoft/broker-mule-app

mvn clean deploy -DmuleDeploy \
  -Danypoint.username=<YOUR_ANYPOINT_USERNAME> \
  -Danypoint.password=<YOUR_ANYPOINT_PASSWORD> \
  -Dcloudhub.environment=Sandbox \
  -Dcloudhub.businessGroup=<YOUR_BG_NAME> \
  -Dcloudhub.region=us-east-1 \
  -Dcloudhub.workerType=SMALL \
  -Dcloudhub.workers=1
```

**After deployment:**
- Note the CloudHub URL: `https://muleops-broker-<random>.cloudhub.io`
- Test: `POST https://<url>/api/broker` with `{"query": "What are the active P1 incidents?"}`

---

## Step 4: Publish Agent Network to Anypoint Exchange

```bash
cd DF/01-mulesoft/agent-network

# Login to Anypoint CLI
anypoint-cli-v4 login --client-id <CLIENT_ID> --client-secret <CLIENT_SECRET>

# Publish the agent network
anypoint-cli-v4 agent-network publish \
  --file agent-network.yaml \
  --org-id <YOUR_ORG_ID> \
  --environment Sandbox
```

**Verify in Anypoint Platform:**
1. Go to Anypoint Platform → Agent Fabric
2. Confirm the network `muleops-intelligence-broker` appears
3. Verify all 3 agents and 1 MCP server are registered
4. Check that consumer sub-agent proxies were auto-created for each agent

---

## Step 5: Register Governance MCP Server in Agent Fabric

```bash
anypoint-cli-v4 mcp-server register \
  --name "mule-app-governance-mcp" \
  --url "https://<governance-mcp-cloudhub-url>/mcp" \
  --org-id <YOUR_ORG_ID> \
  --environment Sandbox
```

---

## Step 6: Apply Flex Gateway Policies

After all agents are behind Flex Gateway (see `05-flex-gateway/DEPLOY.md`), apply policies using the provided YAML files:

```bash
cd DF/01-mulesoft/agent-fabric-config/flex-gateway-policies

# Apply to PagerDuty agent provider instance
anypoint-cli-v4 gateway policy apply \
  --api-instance-id <PAGERDUTY_PROVIDER_INSTANCE_ID> \
  --policy-file client-id-enforcement.yaml

anypoint-cli-v4 gateway policy apply \
  --api-instance-id <PAGERDUTY_PROVIDER_INSTANCE_ID> \
  --policy-file jwt-validation.yaml

anypoint-cli-v4 gateway policy apply \
  --api-instance-id <PAGERDUTY_PROVIDER_INSTANCE_ID> \
  --policy-file rate-limiting.yaml

# Repeat for Splunk and Integration agent provider instances
```

---

## Step 7: Verify the Agent Network

```bash
# Check network status
anypoint-cli-v4 agent-network describe \
  --name muleops-intelligence-broker \
  --org-id <YOUR_ORG_ID>

# Expected output:
# Network: muleops-intelligence-broker
# Status: ACTIVE
# Agents: 3 registered, 3 healthy
# MCP Servers: 1 registered, 1 healthy
# Broker: RUNNING on CloudHub
```

---

## Troubleshooting

| Issue | Likely Cause | Fix |
|---|---|---|
| Broker fails to start | Missing agent URLs in config.yaml | Ensure all 3 agent Flex GW URLs are filled in |
| A2A call returns 401 | Client credentials not injected | Verify consumer sub-agent proxy was created by Agent Fabric |
| A2A call returns 404 | Wrong agent URL | Check Flex GW provider instance URL vs runtime URL |
| LLM routing wrong agent | Skill domain keywords too similar | Tune `routing-rules.yaml` with more specific intents |
| MCP tool call fails | Splunk HEC token expired | Rotate token and redeploy governance MCP server |

---

## Rollback

```bash
# Undeploy broker
anypoint-cli-v4 cloudhub2 application delete muleops-broker --env Sandbox

# Undeploy governance MCP
anypoint-cli-v4 cloudhub2 application delete muleops-governance-mcp --env Sandbox

# Unpublish agent network
anypoint-cli-v4 agent-network delete muleops-intelligence-broker --org-id <ORG_ID>