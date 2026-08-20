"""
PagerDuty API Tools — READ-ONLY wrappers for PagerDuty REST API.
"""
import requests
import logging
from typing import Optional, List, Dict
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)
PD_BASE = "https://api.pagerduty.com"

class PagerDutyTools:
    def __init__(self, api_token: str):
        if not api_token:
            raise ValueError("PAGERDUTY_API_TOKEN is required")
        self.headers = {
            "Authorization": f"Token token={api_token}",
            "Accept": "application/vnd.pagerduty+json;version=2"
        }

    def _get(self, path: str, params: dict = None) -> dict:
        r = requests.get(f"{PD_BASE}{path}", headers=self.headers, params=params, timeout=15)
        r.raise_for_status()
        return r.json()

    def list_incidents(self, status: str = "triggered,acknowledged",
                       urgency: Optional[str] = None, limit: int = 10,
                       since_hours: int = 24) -> List[Dict]:
        since = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat()
        params = {"statuses[]": status.split(","), "limit": min(limit, 25), "since": since}
        if urgency:
            params["urgencies[]"] = urgency
        data = self._get("/incidents", params)
        return [{"id": i["id"], "title": i["title"], "status": i["status"],
                 "urgency": i["urgency"], "created_at": i["created_at"],
                 "service": i["service"]["summary"]} for i in data.get("incidents", [])]

    def get_incident(self, incident_id: str) -> Dict:
        data = self._get(f"/incidents/{incident_id}")
        i = data["incident"]
        return {"id": i["id"], "title": i["title"], "status": i["status"],
                "urgency": i["urgency"], "created_at": i["created_at"],
                "service": i["service"]["summary"],
                "assigned_to": [a["assignee"]["summary"] for a in i.get("assignments", [])]}

    def list_oncall(self, schedule_id: Optional[str] = None, limit: int = 5) -> List[Dict]:
        params = {"limit": limit}
        if schedule_id:
            params["schedule_ids[]"] = schedule_id
        data = self._get("/oncalls", params)
        return [{"user": o["user"]["summary"], "schedule": (o.get("schedule") or {}).get("summary", "N/A"),
                 "start": o["start"], "end": o["end"]} for o in data.get("oncalls", [])]

    def list_services(self, team_id: Optional[str] = None, limit: int = 20) -> List[Dict]:
        params = {"limit": limit}
        if team_id:
            params["team_ids[]"] = team_id
        data = self._get("/services", params)
        return [{"id": s["id"], "name": s["name"], "status": s["status"],
                 "description": s.get("description", "")} for s in data.get("services", [])]

    def list_escalation_policies(self, name: Optional[str] = None, limit: int = 10) -> List[Dict]:
        params = {"limit": limit}
        if name:
            params["query"] = name
        data = self._get("/escalation_policies", params)
        return [{"id": p["id"], "name": p["name"],
                 "num_loops": p.get("num_loops", 0)} for p in data.get("escalation_policies", [])]

    def list_teams(self, limit: int = 20) -> List[Dict]:
        data = self._get("/teams", {"limit": limit})
        return [{"id": t["id"], "name": t["name"],
                 "description": t.get("description", "")} for t in data.get("teams", [])]