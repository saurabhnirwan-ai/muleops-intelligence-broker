# Slack Integration Setup Guide

## Overview

Connects a Slack app to the MuleOps broker so ops engineers can ask
operational questions in Slack and receive consolidated, formatted answers.

---

## Step 1: Create the Slack App

1. Go to https://api.slack.com/apps → **Create New App** → **From manifest**
2. Paste the manifest below (update the `request_url` to your broker URL)
3. Click **Create**
4. Under **OAuth & Permissions** → **Install to Workspace**
5. Note the **Bot User OAuth Token** (`xoxb-...`) — add to broker `.env` as `SLACK_BOT_TOKEN`

### Slack App Manifest

```yaml
display_information:
  name: MuleOps Intelligence Broker
  description: Unified operational intelligence — ask about incidents, logs, and CloudHub apps in natural language.
  background_color: "#1B3D6E"

features:
  bot_user:
    display_name: MuleOps Intelligence Broker
    always_online: true
  app_home:
    home_tab_enabled: true
    messages_tab_enabled: true

oauth_config:
  scopes:
    bot:
      - chat:write
      - app_mentions:read
      - channels:history
      - channels:read
      - im:history
      - im:write
      - im:read

settings:
  event_subscriptions:
    request_url: "https://<YOUR_BROKER_URL>/api/slack/events"
    bot_events:
      - app_mention
      - message.im
  interactivity:
    is_enabled: false
  org_deploy_enabled: false
  socket_mode_enabled: false
```

> **Current demo URL** (Cloudflare tunnel):
> `https://historic-favorite-attributes-southern.trycloudflare.com/api/slack/events`

---

## Step 2: Configure Event Subscriptions

1. In your Slack App → **Event Subscriptions** → Enable
2. Set **Request URL** to your broker `/api/slack/events` endpoint
3. Slack will send a `url_verification` challenge — the broker handles this automatically
4. Subscribe to bot events: `app_mention`, `message.im`

---

## Step 3: Invite the Bot to a Channel

```
/invite @MuleOps Intelligence Broker
```

---

## Step 4: Test

In Slack, type:
```
@MuleOps Intelligence Broker What are the active P1 incidents right now?
```

Expected: Bot replies within 5–15 seconds with live PagerDuty data.

---

## Sample Queries (Copy-Paste Ready)

### PagerDuty Queries
```
@MuleOps What are the active P1 incidents right now?
@MuleOps Show me all incidents triggered in the last 2 hours
@MuleOps Who is currently on-call for the integration team?
@MuleOps What is the escalation policy for BT-INTEGRATION?
@MuleOps How many incidents were triggered this week?
@MuleOps List all PagerDuty services for the integration team
```

### Splunk Queries
```
@MuleOps Search for ERROR logs in mule-app-gateway in the last hour
@MuleOps What are the top 10 most frequent errors in the last 24 hours?
@MuleOps Find all timeout errors across all apps in production
@MuleOps Are there any critical ADO alerts active right now?
@MuleOps What ADO alerts fired in the last 15 minutes?
@MuleOps Search Splunk for exceptions from the payment-processing app today
```

### CloudHub / Integration Queries
```
@MuleOps How many apps in BT-INTEGRATION are not running Java 17?
@MuleOps What are the top 5 applications consuming the most vCores?
@MuleOps Show me all applications with static IPs in production
@MuleOps How many vCores are allocated across the BT-INTEGRATION business group?
@MuleOps Which apps are running on deprecated runtime versions?
```

### Governance MCP Queries
```
@MuleOps Check compliance status for mule-payment-api in Production
@MuleOps Log an ADO alert: CRITICAL - mule-payment-api missing client access approval
@MuleOps Generate a compliance report for all apps in BT-INTEGRATION
```

### Meta / Capability Queries
```
@MuleOps What can you do?
@MuleOps Hello
@MuleOps Help
@MuleOps What agents do you have?
```

### Multi-Domain Queries
```
@MuleOps Find the app with the most errors and check if there's an active incident for it
@MuleOps Is mule-app-gateway having issues? Check logs and any active alerts