# Integration System Agent (Agentforce A2A Wrapper) — Deployment Guide

## What This Is

A Python FastAPI wrapper that exposes an existing **Salesforce Agentforce Service Agent**
as an A2A-compliant endpoint. The wrapper translates A2A protocol requests into
Agentforce Agent API calls, making the Salesforce agent accessible to any
A2A consumer (including the MuleOps broker).

## Prerequisites

- Python 3.11+, Docker
- Heroku CLI (`npm install -g heroku`) or any container host
- Salesforce org with Agentforce Service Agent already configured
  - Topics defined for CloudHub app queries
  - Actions configured (SOQL to Salesforce Data Cloud)
  - Connected App with OAuth 2.0 credentials

---

## Step 1: Configure Salesforce (One-time Setup)

### 1.1 Create a Connected App in Salesforce
1. Setup → App Manager → New Connected App
2. Enable OAuth Settings
3. Scopes: `api`, `refresh_token`, `agentforce`
4. Note the **Client ID** and **Client Secret**

### 1.2 Get the Agentforce Agent ID
```bash
# Via Salesforce CLI
sf agent list --target-org <YOUR_ORG>
# Note the Agent ID (starts with 0Xx...)
```

---

## Step 2: Configure Environment Variables

```bash
cp .env.example .env
```

Edit `.env`:
```
SF_CLIENT_ID=<YOUR_SALESFORCE_CONNECTED_APP_CLIENT_ID>
SF_CLIENT_SECRET=<YOUR_SALESFORCE_CONNECTED_APP_CLIENT_SECRET>
SF_INSTANCE_URL=https://<YOUR_ORG>.my.salesforce.com
SF_AGENT_ID=<YOUR_AGENTFORCE_AGENT_ID>
SF_AGENT_API_BASE_URL=https://api.salesforce.com
PORT=8080
```

---

## Step 3: Run Locally

```bash
pip install -r requirements.txt
python app.py
```

Test:
```bash
curl -X POST http://localhost:8080/a2a \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tasks/send",
    "id": "test-001",
    "params": {
      "id": "task-001",
      "message": {"role": "user", "parts": [{"text": "How many apps in BT-INTEGRATION are not running Java 17?"}]}
    }
  }'
```

---

## Step 4: Deploy to Heroku

```bash
# Login to Heroku
heroku login

# Create app
heroku create muleops-integration-agent

# Set environment variables
heroku config:set SF_CLIENT_ID=<VALUE> SF_CLIENT_SECRET=<VALUE> \
  SF_INSTANCE_URL=<VALUE> SF_AGENT_ID=<VALUE> \
  SF_AGENT_API_BASE_URL=https://api.salesforce.com \
  --app muleops-integration-agent

# Deploy via container
heroku container:push web --app muleops-integration-agent
heroku container:release web --app muleops-integration-agent

# Verify
heroku logs --tail --app muleops-integration-agent
```

**After deployment:**
- Note the Heroku URL: `https://muleops-integration-agent.herokuapp.com`
- Register this URL behind Flex Gateway (see `05-flex-gateway/DEPLOY.md`)
- Add the Flex Gateway provider URL to broker `config.yaml`

---

## Troubleshooting

| Issue | Fix |
|---|---|
| 401 from Salesforce token endpoint | Verify Connected App Client ID/Secret |
| Agent session creation fails | Check Agentforce Agent ID is correct and confirm `SF_AGENT_API_BASE_URL` is `https://api.salesforce.com` or `https://api.gov.salesforce.com` as appropriate |
| Empty response from agent | Ensure topics/actions are configured in Agentforce for CloudHub queries |
| Heroku container push fails | Run `heroku container:login` first |
