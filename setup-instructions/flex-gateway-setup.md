# Flex Gateway Setup Guide

## Overview

Flex Gateway sits in front of every specialist agent and MCP server, implementing
the **Delegated Agent Egress** pattern — two instances per agent:

- **Provider instance** — hard security perimeter in front of the agent runtime
- **Consumer instance** — auto-created by Agent Fabric when the network deploys

---

## Prerequisites

- Anypoint CLI v4: `npm install -g anypoint-cli-v4`
- Flex Gateway registered in Anypoint Platform
- Network access to all agent runtimes (EC2, CloudHub)

---

## Step 1: Register Flex Gateway

### Option A: Managed Flex Gateway (Recommended for Demo)

```bash
anypoint-cli-v4 gateway create \
  --name muleops-flex-gateway \
  --type managed \
  --environment Sandbox \
  --org-id <YOUR_ORG_ID>
```

### Option B: Self-Managed (Docker)

```bash
docker pull mulesoft/flex-gateway:latest
anypoint-cli-v4 gateway register \
  --name muleops-flex-gateway \
  --environment Sandbox \
  --output registration.yaml

docker run -d \
  -v $(pwd)/registration.yaml:/usr/local/share/mulesoft/flex-gateway/conf.d/registration.yaml \
  -p 443:443 \
  mulesoft/flex-gateway:latest
```

### Registration YAML Template

```yaml
apiVersion: gateway.mulesoft.com/v1alpha1
kind: Configuration
metadata:
  name: muleops-flex-gateway
spec:
  platformConnection:
    url: https://anypoint.mulesoft.com
    organizationId: "<YOUR_ORG_ID>"
    environmentId: "<YOUR_SANDBOX_ENV_ID>"
  gateway:
    name: muleops-flex-gateway
    replicaCount: 1
    resources:
      requests:
        memory: "256Mi"
        cpu: "100m"
      limits:
        memory: "512Mi"
        cpu: "500m"
  logging:
    level: INFO
    runtimeLogs:
      enabled: true
```

---

## Step 2: Create API Instances for Each Agent

```bash
# PagerDuty Agent Provider Instance
anypoint-cli-v4 api-manager create-api \
  --name "muleops-pagerduty-agent-provider" \
  --upstream-url "http://3.129.60.192:8080" \
  --type http --environment Sandbox --org-id <YOUR_ORG_ID>
# Note returned ID as PAGERDUTY_INSTANCE_ID

# Splunk Agent Provider Instance
anypoint-cli-v4 api-manager create-api \
  --name "muleops-splunk-agent-provider" \
  --upstream-url "http://3.129.60.192:8081" \
  --type http --environment Sandbox --org-id <YOUR_ORG_ID>
# Note returned ID as SPLUNK_INSTANCE_ID

# Integration System Agent Provider Instance
anypoint-cli-v4 api-manager create-api \
  --name "muleops-integration-agent-provider" \
  --upstream-url "http://3.129.60.192:8082" \
  --type http --environment Sandbox --org-id <YOUR_ORG_ID>
# Note returned ID as INTEGRATION_INSTANCE_ID

# Governance MCP Server Provider Instance
anypoint-cli-v4 api-manager create-api \
  --name "muleops-governance-mcp-provider" \
  --upstream-url "https://<GOVERNANCE_MCP_CLOUDHUB_URL>/mcp" \
  --type http --environment Sandbox --org-id <YOUR_ORG_ID>
# Note returned ID as GOVERNANCE_MCP_INSTANCE_ID
```

---

## Step 3: Apply Policies to All Provider Instances

```bash
for INSTANCE_ID in $PAGERDUTY_INSTANCE_ID $SPLUNK_INSTANCE_ID $INTEGRATION_INSTANCE_ID $GOVERNANCE_MCP_INSTANCE_ID; do

  # Client-ID Enforcement
  anypoint-cli-v4 api-manager apply-policy \
    --api-instance-id $INSTANCE_ID \
    --policy-template-id client-id-enforcement \
    --org-id <YOUR_ORG_ID> --environment Sandbox

  # JWT Validation
  anypoint-cli-v4 api-manager apply-policy \
    --api-instance-id $INSTANCE_ID \
    --policy-template-id jwt-validation \
    --org-id <YOUR_ORG_ID> --environment Sandbox

  # Rate Limiting (60 req/min)
  anypoint-cli-v4 api-manager apply-policy \
    --api-instance-id $INSTANCE_ID \
    --policy-template-id rate-limiting \
    --config '{"rateLimits":[{"maximumRequests":60,"timePeriodInMilliseconds":60000}]}' \
    --org-id <YOUR_ORG_ID> --environment Sandbox
done

# MCP PII Detector — Governance MCP Server ONLY
anypoint-cli-v4 api-manager apply-policy \
  --api-instance-id $GOVERNANCE_MCP_INSTANCE_ID \
  --policy-template-id mcp-pii-detector \
  --org-id <YOUR_ORG_ID> --environment Sandbox
```

---

## Step 4: Update Broker Config with Flex GW URLs

After setup, update `01-mulesoft/broker-mule-app/src/main/resources/config.yaml`:

```yaml
pagerduty.agent.url: "https://<flex-gateway-host>/muleops-pagerduty-agent-provider"
splunk.agent.url:    "https://<flex-gateway-host>/muleops-splunk-agent-provider"
integration.agent.url: "https://<flex-gateway-host>/muleops-integration-agent-provider"
governance.mcp.url:  "https://<flex-gateway-host>/muleops-governance-mcp-provider"
```

---

## Step 5: Verify

```bash
curl -X POST https://<flex-gateway-host>/muleops-pagerduty-agent-provider/a2a \
  -H "client_id: <TEST_CLIENT_ID>" \
  -H "client_secret: <TEST_CLIENT_SECRET>" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tasks/send","id":"test","params":{"id":"t1","message":{"role":"user","parts":[{"text":"health check"}]}}}'
```

Expected: 200 response (not 401 or 403).

---

## Troubleshooting

| Issue | Fix |
|---|---|
| 401 Unauthorized | Client-ID or credentials not configured correctly |
| 502 Bad Gateway | Agent runtime URL incorrect or agent not running |
| 404 Not Found | API instance not associated with the Flex Gateway |
| Policy not applying | Check policy template ID — use exact names from Anypoint Exchange |