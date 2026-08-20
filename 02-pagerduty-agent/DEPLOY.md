# PagerDuty Specialist Agent — Deployment Guide

## What This Is

A Python FastAPI application implementing the A2A (Agent-to-Agent) protocol.
It receives natural-language queries about PagerDuty, translates them into
PagerDuty API calls using Claude Sonnet via AWS Bedrock, and returns
structured responses to the MuleOps broker.

## Prerequisites

- Python 3.11+
- Docker
- AWS account with Bedrock access (Claude Sonnet enabled in your region)
- PagerDuty account with a read-only API token
- AWS App Runner service (or any container host)

---

## Step 1: Configure Environment Variables

Copy `.env.example` to `.env` and fill in all values:

```bash
cp .env.example .env
```

Edit `.env`:
```
PAGERDUTY_API_TOKEN=<YOUR_PAGERDUTY_READ_ONLY_API_TOKEN>
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=<YOUR_AWS_ACCESS_KEY_ID>
AWS_SECRET_ACCESS_KEY=<YOUR_AWS_SECRET_ACCESS_KEY>
BEDROCK_MODEL_ID=anthropic.claude-sonnet-4-5
PORT=8080
```

---

## Step 2: Run Locally (for testing)

```bash
cd DF/02-pagerduty-agent
pip install -r requirements.txt
python app.py
```

Test the A2A endpoint:
```bash
curl -X POST http://localhost:8080/a2a \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tasks/send",
    "id": "test-001",
    "params": {
      "id": "task-001",
      "message": {
        "role": "user",
        "parts": [{"text": "What are the active P1 incidents?"}]
      }
    }
  }'
```

---

## Step 3: Build and Push Docker Image

```bash
# Build
docker build -t muleops-pagerduty-agent:1.0.0 .

# Tag for ECR (replace with your AWS account ID and region)
docker tag muleops-pagerduty-agent:1.0.0 \
  <AWS_ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com/muleops-pagerduty-agent:1.0.0

# Login to ECR
aws ecr get-login-password --region <REGION> | \
  docker login --username AWS --password-stdin \
  <AWS_ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com

# Create ECR repository (first time only)
aws ecr create-repository --repository-name muleops-pagerduty-agent

# Push
docker push <AWS_ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com/muleops-pagerduty-agent:1.0.0
```

---

## Step 4: Deploy to AWS App Runner

```bash
# Create App Runner service using the provided config
aws apprunner create-service --cli-input-json file://apprunner.yaml

# Or via AWS Console:
# 1. Go to AWS App Runner → Create Service
# 2. Source: Container registry → Amazon ECR
# 3. Image URI: <ECR_URI>/muleops-pagerduty-agent:1.0.0
# 4. Port: 8080
# 5. Set all environment variables from .env
# 6. Health check path: /health
```

**After deployment:**
- Note the App Runner service URL: `https://<random>.awsapprunner.com`
- This URL goes into Flex Gateway as the upstream (provider instance)
- Then into the broker's `config.yaml` as `pagerduty.agent.url` (via Flex GW)

---

## Step 5: Register Behind Flex Gateway

See `05-flex-gateway/DEPLOY.md` for full instructions.

Quick summary:
```bash
# Register provider instance in API Manager
anypoint-cli-v4 api-manager create-api \
  --name "muleops-pagerduty-agent-provider" \
  --endpoint "https://<APP_RUNNER_URL>/a2a" \
  --type http

# Register Flex Gateway as proxy
anypoint-cli-v4 gateway policy apply \
  --api-instance-id <PROVIDER_INSTANCE_ID> \
  --policy-file ../01-mulesoft/agent-fabric-config/flex-gateway-policies/client-id-enforcement.yaml
```

---

## Troubleshooting

| Issue | Fix |
|---|---|
| Bedrock returns 403 | Ensure `anthropic.claude-sonnet-4-5` is enabled in your AWS region's Bedrock console |
| PagerDuty returns 401 | Verify token is read-only API token, not OAuth |
| App Runner health check fails | Ensure `GET /health` returns 200 |
| A2A returns empty artifacts | Check Bedrock model response parsing in `app.py` |