# Testing Guide — MuleOps Intelligence Broker

## Testing Order

```
1. Health checks          — all 4 services UP
2. Direct A2A tests       — each agent responds correctly
3. Broker routing tests   — each domain routes correctly
4. Flex GW security tests — client-ID enforcement works
5. End-to-end latency     — under 15 seconds
```

---

## 1. Health Checks (Run Before Every Demo)

```bash
# Quick all-in-one check
for port in 8080 8081 8082 9000; do
  echo -n "Port $port: "
  curl -s --max-time 5 http://3.129.60.192:$port/health
  echo ""
done
```

Expected — all four return `{"status":"UP",...}`:
```
Port 8080: {"status":"UP","service":"muleops-pagerduty-agent","version":"1.0.0"}
Port 8081: {"status":"UP","service":"muleops-splunk-agent","version":"1.0.0"}
Port 8082: {"status":"UP","service":"muleops-integration-agent","version":"1.0.0"}
Port 9000: {"status":"UP","service":"muleops-demo-broker","version":"1.0.0"}
```

---

## 2. Direct A2A Agent Tests (No Broker)

```bash
BASE="http://3.129.60.192"

# PagerDuty Agent
curl -s -X POST $BASE:8080/a2a \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tasks/send","id":"t1","params":{"id":"task-1","message":{"role":"user","parts":[{"text":"what are the active incidents?"}]}}}' \
  | python3 -m json.tool

# Splunk Agent
curl -s -X POST $BASE:8081/a2a \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tasks/send","id":"t2","params":{"id":"task-2","message":{"role":"user","parts":[{"text":"show me error logs in the last hour"}]}}}' \
  | python3 -m json.tool

# Integration Agent
curl -s -X POST $BASE:8082/a2a \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tasks/send","id":"t3","params":{"id":"task-3","message":{"role":"user","parts":[{"text":"how many apps in BT-INTEGRATION are not running Java 17?"}]}}}' \
  | python3 -m json.tool
```

Expected: Each returns `"result.status.state": "completed"` with text in `artifacts[0].parts[0].text`.

---

## 3. Broker Routing Tests

```bash
BASE="http://3.129.60.192:9000/api/broker"

# PagerDuty routing
curl -s -X POST $BASE -H "Content-Type: application/json" \
  -d '{"query":"What are the active P1 incidents right now?"}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('routedTo:', d['routedTo'])"

# Splunk routing
curl -s -X POST $BASE -H "Content-Type: application/json" \
  -d '{"query":"Search for ERROR logs in the last hour"}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('routedTo:', d['routedTo'])"

# Integration routing
curl -s -X POST $BASE -H "Content-Type: application/json" \
  -d '{"query":"How many apps in BT-INTEGRATION are not running Java 17?"}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('routedTo:', d['routedTo'])"

# Meta routing (should NOT route to PagerDuty)
curl -s -X POST $BASE -H "Content-Type: application/json" \
  -d '{"query":"what can you do?"}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('routedTo:', d['routedTo'])"
```

Expected routedTo values:
```
pagerduty-specialist
splunk-ops-specialist
integration-system-agent
broker-meta
```

---

## 4. OBO Token Test

```bash
# Send A2A request with OBO headers directly to PagerDuty agent
curl -s -X POST http://3.129.60.192:8080/a2a \
  -H "Content-Type: application/json" \
  -H "X-OBO-Token: eyJzbGFja191c2VyX2lkIjoidGVzdCJ9" \
  -H "X-Initiated-By: U_TEST_USER" \
  -H "X-Correlation-ID: test-obo-001" \
  -d '{"jsonrpc":"2.0","method":"tasks/send","id":"test-obo","params":{"id":"task-obo","message":{"role":"user","parts":[{"text":"what are the active incidents?"}]}}}' \
  | python3 -m json.tool

# Verify OBO headers appear in agent logs
ssh -i ~/.ssh/muleops-ec2-key.pem ec2-user@3.129.60.192 \
  "tail -10 ~/pagerduty-agent.log | grep -E 'OBO|InitiatedBy|CorrelationID'"
```

---

## 5. End-to-End Latency

```bash
time curl -s -X POST http://3.129.60.192:9000/api/broker \
  -H "Content-Type: application/json" \
  -d '{"query":"What are the active P1 incidents right now?"}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('routedTo:', d['routedTo'])"
```

**Target SLA:** Under 15 seconds total.

---

## Expected Response Shape (Broker)

```json
{
  "correlationId": "550e8400-e29b-41d4-a716-446655440000",
  "query": "What are the active P1 incidents right now?",
  "routedTo": "pagerduty-specialist",
  "initiatedBy": "api-direct",
  "response": "There are currently 2 active P1 incidents:\n\n• INC-12345 ...",
  "timestamp": "2026-11-08T07:10:00Z"
}
```

---

## Sample Payloads

### PagerDuty Query
```json
{
  "jsonrpc": "2.0",
  "method": "tasks/send",
  "id": "req-pd-001",
  "params": {
    "id": "task-pd-001",
    "message": {
      "role": "user",
      "parts": [{"text": "What are the active P1 incidents right now?"}]
    }
  }
}
```

### Splunk Query
```json
{
  "jsonrpc": "2.0",
  "method": "tasks/send",
  "id": "req-splunk-001",
  "params": {
    "id": "task-splunk-001",
    "message": {
      "role": "user",
      "parts": [{"text": "Show me ERROR logs from mule-app-gateway in the last hour"}]
    }
  }
}
```

### CloudHub Query
```json
{
  "jsonrpc": "2.0",
  "method": "tasks/send",
  "id": "req-cf-001",
  "params": {
    "id": "task-cf-001",
    "message": {
      "role": "user",
      "parts": [{"text": "How many apps in BT-INTEGRATION are not running Java 17?"}]
    }
  }
}
```

---

## Troubleshooting Quick Reference

| Symptom | Check |
|---|---|
| Agent health check fails | SSH to EC2 and check `tail -20 ~/pagerduty-agent.log` |
| Broker returns wrong `routedTo` | Query may be ambiguous — check Tier 3 Gemini classification |
| Empty agent response | Check PagerDuty/Splunk/Salesforce credentials in `.env` |
| Integration agent slow | Salesforce session creation dominates — normal, ~8–20 sec |
| OBO token not in logs | Confirm broker is forwarding `X-OBO-Token` header |
| Port 8082 unreachable | Check AWS security group `sg-06f0b60fd72cdaff7` includes port 8082 |