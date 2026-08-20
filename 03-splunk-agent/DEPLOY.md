# Splunk Ops Specialist Agent — Deployment Guide

## What This Is

A Python FastAPI A2A agent for Splunk log search, SPL query generation, and
ADO alert monitoring. Uses Claude Sonnet via AWS Bedrock to translate
natural-language queries into Splunk SPL searches.

## Prerequisites

- Python 3.11+, Docker, AWS Bedrock access (Claude Sonnet)
- Splunk instance with REST API access (port 8089) or HEC token
- AWS App Runner (or any container host)

---

## Step 1: Configure Environment Variables

```bash
cp .env.example .env
```

Edit `.env`:
```
SPLUNK_HOST=<YOUR_SPLUNK_HOST>
SPLUNK_TOKEN=<YOUR_SPLUNK_REST_API_TOKEN>
SPLUNK_PORT=8089
SPLUNK_SCHEME=https
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=<YOUR_AWS_ACCESS_KEY_ID>
AWS_SECRET_ACCESS_KEY=<YOUR_AWS_SECRET_ACCESS_KEY>
BEDROCK_MODEL_ID=anthropic.claude-sonnet-4-5
PORT=8080
```

---

## Step 2: Run Locally

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
      "message": {"role": "user", "parts": [{"text": "Search for ERROR logs in mule-app-gateway in the last hour"}]}
    }
  }'
```

---

## Step 3: Build, Push, Deploy (same as PagerDuty agent)

```bash
docker build -t muleops-splunk-agent:1.0.0 .
docker tag muleops-splunk-agent:1.0.0 <ECR_URI>/muleops-splunk-agent:1.0.0
docker push <ECR_URI>/muleops-splunk-agent:1.0.0
aws apprunner create-service --cli-input-json file://apprunner.yaml
```

After deployment, note the App Runner URL and register it behind Flex Gateway.

---

## Troubleshooting

| Issue | Fix |
|---|---|
| Splunk returns 401 | Check token type: use Bearer token for REST API |
| SPL syntax error | Review `splunk_tools.py` — the generated SPL may need tuning |
| Bedrock returns 403 | Enable Claude Sonnet in AWS Bedrock console for your region |
| Empty search results | Verify Splunk index names match your environment |