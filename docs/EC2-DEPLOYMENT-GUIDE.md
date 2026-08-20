# EC2 Deployment Guide — MuleOps Intelligence Broker
## Instance Details (Current)
- **Public IP**: 3.129.60.192
- **Instance ID**: i-0c38a27367be63046
- **Region**: us-east-2 (Ohio)
- **Type**: t3.small
- **OS**: Amazon Linux 2023
- **SSH Key**: ~/.ssh/muleops-ec2-key.pem

---

## 1. SSH Into the Instance

```bash
ssh -i ~/.ssh/muleops-ec2-key.pem ec2-user@3.129.60.192
```

> **Key location**: `/Users/Vanshiv/.ssh/muleops-ec2-key.pem`
> Permissions must be 400: `chmod 400 ~/.ssh/muleops-ec2-key.pem`

---

## 2. Agent Locations on the Instance

| Agent | Directory | Port | Log File |
|-------|-----------|------|----------|
| PagerDuty Specialist | `/opt/pagerduty-agent/` | 8080 | `~/pagerduty-agent.log` |
| Splunk Ops Specialist | `/opt/splunk-agent/` | 8081 | `~/splunk-agent.log` |
| Integration System | `/opt/integration-agent/` | 8082 | `~/integration-agent.log` |

---

## 3. Check Agent Health

```bash
curl http://3.129.60.192:8080/health   # PagerDuty
curl http://3.129.60.192:8081/health   # Splunk
curl http://3.129.60.192:8082/health   # Integration
```

Or check all at once from your Mac:
```bash
for port in 8080 8081 8082; do
  echo "Port $port: $(curl -s http://3.129.60.192:$port/health)"
done
```

---

## 4. Deploy Updated Code to EC2

### Deploy a single file
```bash
scp -i ~/.ssh/muleops-ec2-key.pem <local-file> ec2-user@3.129.60.192:<remote-path>
```

**Example — update PagerDuty agent:**
```bash
scp -i ~/.ssh/muleops-ec2-key.pem \
  02-pagerduty-agent/app.py \
  02-pagerduty-agent/pagerduty_tools.py \
  ec2-user@3.129.60.192:/opt/pagerduty-agent/
```

**Example — update Splunk agent:**
```bash
scp -i ~/.ssh/muleops-ec2-key.pem \
  03-splunk-agent/app.py \
  03-splunk-agent/splunk_tools.py \
  ec2-user@3.129.60.192:/opt/splunk-agent/
```

**Example — update Integration agent:**
```bash
scp -i ~/.ssh/muleops-ec2-key.pem \
  04-integration-system-agent/app.py \
  04-integration-system-agent/agentforce_client.py \
  ec2-user@3.129.60.192:/opt/integration-agent/
```

---

## 5. Restart an Agent

After copying updated files, restart the agent on the specific port:

```bash
# PagerDuty Agent (port 8080)
ssh -i ~/.ssh/muleops-ec2-key.pem ec2-user@3.129.60.192 \
  "fuser -k 8080/tcp 2>/dev/null; sleep 1; cd /opt/pagerduty-agent && nohup python3 app.py > ~/pagerduty-agent.log 2>&1 &"

# Splunk Agent (port 8081)
ssh -i ~/.ssh/muleops-ec2-key.pem ec2-user@3.129.60.192 \
  "fuser -k 8081/tcp 2>/dev/null; sleep 1; cd /opt/splunk-agent && nohup python3 app.py > ~/splunk-agent.log 2>&1 &"

# Integration Agent (port 8082) — requires env export due to dotenv path issue
ssh -i ~/.ssh/muleops-ec2-key.pem ec2-user@3.129.60.192 \
  "fuser -k 8082/tcp 2>/dev/null; sleep 1; cd /opt/integration-agent && export \$(cat .env | grep -v '^#' | xargs) && nohup python3 app.py > ~/integration-agent.log 2>&1 &"
```

---

## 6. Deploy a New Agent from Scratch

Run this once on the EC2 instance (or pass via SSH) to set up a new agent:

```bash
ssh -i ~/.ssh/muleops-ec2-key.pem ec2-user@3.129.60.192 << 'EOF'
# Create directory
sudo mkdir -p /opt/my-new-agent
sudo chown ec2-user:ec2-user /opt/my-new-agent

# Install Python dependencies (if new packages needed)
pip3 install <package-name>

# Create .env file
cat > /opt/my-new-agent/.env << 'ENVEOF'
MY_API_KEY=xxx
PORT=8083
ENVEOF

# Start the agent
cd /opt/my-new-agent
nohup python3 app.py > ~/my-new-agent.log 2>&1 &
sleep 3
curl -s http://localhost:8083/health
EOF
```

---

## 7. View Logs

```bash
# View live logs
ssh -i ~/.ssh/muleops-ec2-key.pem ec2-user@3.129.60.192 "tail -f ~/pagerduty-agent.log"
ssh -i ~/.ssh/muleops-ec2-key.pem ec2-user@3.129.60.192 "tail -f ~/splunk-agent.log"
ssh -i ~/.ssh/muleops-ec2-key.pem ec2-user@3.129.60.192 "tail -f ~/integration-agent.log"

# View last 50 lines
ssh -i ~/.ssh/muleops-ec2-key.pem ec2-user@3.129.60.192 "tail -50 ~/pagerduty-agent.log"

# Search for errors
ssh -i ~/.ssh/muleops-ec2-key.pem ec2-user@3.129.60.192 "grep -i error ~/splunk-agent.log | tail -20"
```

---

## 8. Check Running Processes

```bash
ssh -i ~/.ssh/muleops-ec2-key.pem ec2-user@3.129.60.192 "ps aux | grep python3 | grep -v grep"
```

---

## 9. Stop an Agent

```bash
# Stop by port
ssh -i ~/.ssh/muleops-ec2-key.pem ec2-user@3.129.60.192 "fuser -k 8080/tcp"  # PagerDuty
ssh -i ~/.ssh/muleops-ec2-key.pem ec2-user@3.129.60.192 "fuser -k 8081/tcp"  # Splunk
ssh -i ~/.ssh/muleops-ec2-key.pem ec2-user@3.129.60.192 "fuser -k 8082/tcp"  # Integration

# Stop all agents at once
ssh -i ~/.ssh/muleops-ec2-key.pem ec2-user@3.129.60.192 "fuser -k 8080/tcp 8081/tcp 8082/tcp 2>/dev/null"
```

---

## 10. Update Environment Variables

```bash
# Add or update a variable in an agent's .env
ssh -i ~/.ssh/muleops-ec2-key.pem ec2-user@3.129.60.192 \
  "echo 'NEW_VAR=value' >> /opt/pagerduty-agent/.env"

# Rewrite .env completely (safest — avoids missing newline issues)
ssh -i ~/.ssh/muleops-ec2-key.pem ec2-user@3.129.60.192 \
  "printf 'KEY1=value1\nKEY2=value2\nPORT=8080\n' > /opt/pagerduty-agent/.env"
```

---

## 11. Install New Python Packages

```bash
ssh -i ~/.ssh/muleops-ec2-key.pem ec2-user@3.129.60.192 "pip3 install <package-name>"
```

---

## 12. Test an Agent's A2A Endpoint

```bash
# Test PagerDuty agent
curl -s -X POST http://3.129.60.192:8080/a2a \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tasks/send",
    "id": "test-1",
    "params": {
      "id": "task-001",
      "message": {
        "role": "user",
        "parts": [{"text": "What are the active incidents?"}]
      }
    }
  }' | python3 -m json.tool

# Test Splunk agent
curl -s -X POST http://3.129.60.192:8081/a2a \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tasks/send",
    "id": "test-2",
    "params": {
      "id": "task-002",
      "message": {
        "role": "user",
        "parts": [{"text": "Show me ERROR logs from mule_apps in the last hour"}]
      }
    }
  }' | python3 -m json.tool

# Test Integration agent
curl -s -X POST http://3.129.60.192:8082/a2a \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tasks/send",
    "id": "test-3",
    "params": {
      "id": "task-003",
      "message": {
        "role": "user",
        "parts": [{"text": "What are the top 5 applications consuming the most vCores?"}]
      }
    }
  }' | python3 -m json.tool
```

---

## 13. Recreate the Instance (If Needed)

If you ever need to replace this EC2 instance again:

```bash
# 1. Create new key pair (saves .pem to ~/.ssh/)
aws ec2 create-key-pair --region us-east-2 --key-name muleops-ec2-key \
  --query "KeyMaterial" --output text > ~/.ssh/muleops-ec2-key.pem
chmod 400 ~/.ssh/muleops-ec2-key.pem

# 2. Launch new instance (same config)
aws ec2 run-instances \
  --region us-east-2 \
  --image-id ami-06dd88604c99ec11f \
  --instance-type t3.small \
  --key-name muleops-ec2-key \
  --security-group-ids sg-06f0b60fd72cdaff7 \
  --subnet-id subnet-0cf23196aa408d7f8 \
  --associate-public-ip-address \
  --iam-instance-profile Name=MuleopsEC2Profile \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=muleops-agents}]' \
  --query "Instances[0].{InstanceId:InstanceId,State:State.Name}" \
  --output json --no-paginate

# 3. Wait for it to be running
aws ec2 wait instance-running --region us-east-2 --instance-ids <new-instance-id> --no-paginate

# 4. Get new public IP
aws ec2 describe-instances --region us-east-2 --instance-ids <new-instance-id> \
  --query "Reservations[0].Instances[0].PublicIpAddress" --output text --no-paginate

# 5. Terminate old instance
aws ec2 terminate-instances --region us-east-2 --instance-ids <old-instance-id> --no-paginate
```

---

## 14. AWS Instance Specs Reference

| Parameter | Value |
|-----------|-------|
| AMI | `ami-06dd88604c99ec11f` (Amazon Linux 2023) |
| Instance Type | `t3.small` |
| Region | `us-east-2` (Ohio) |
| Availability Zone | `us-east-2b` |
| Security Group | `sg-06f0b60fd72cdaff7` |
| Subnet | `subnet-0cf23196aa408d7f8` |
| VPC | `vpc-00f1fd9c270ed1035` |
| IAM Profile | `MuleopsEC2Profile` |
| SSH Key | `muleops-ec2-key` → `~/.ssh/muleops-ec2-key.pem` |