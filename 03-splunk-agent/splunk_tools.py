"""
Splunk REST API tools — READ-ONLY search operations.
Supports live Splunk via REST API and demo/mock mode when Splunk is unreachable.
"""
import requests
import time
import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Dict

logger = logging.getLogger(__name__)

# Realistic mock log data for demo mode
MOCK_APPS = ["mule-app-gateway", "mule-payment-api", "mule-customer-api", "mule-order-processor"]
MOCK_ERRORS = [
    "org.mule.api.MessagingException: HTTP request timeout after 30000ms",
    "java.lang.NullPointerException: Cannot invoke method on null object",
    "com.mule.connector.ConnectorException: Connection refused to downstream service",
    "DataWeave transformation error: Cannot coerce String to Number",
    "Retry policy exhausted after 3 attempts — circuit breaker OPEN"
]


def _mock_results(spl: str, count: int = 10) -> Dict:
    """Generate realistic mock Splunk results for demo purposes."""
    now = datetime.now(timezone.utc)
    results = []
    for _ in range(count):
        app = random.choice(MOCK_APPS)
        mins_ago = random.randint(1, 60)
        ts = (now - timedelta(minutes=mins_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
        results.append({
            "_time": ts,
            "source": app,
            "sourcetype": "mule:app",
            "level": "ERROR",
            "_raw": f"[{ts}] ERROR {app} - {random.choice(MOCK_ERRORS)}"
        })
    return {
        "spl": spl,
        "result_count": count,
        "results": results,
        "note": "DEMO MODE — Splunk Cloud REST API not reachable from this network. Results are simulated for demonstration."
    }


class SplunkTools:
    def __init__(self, host: str, token: str, port: int = 8089, scheme: str = "https"):
        self.host = host
        self.token = token
        self.base_url = f"{scheme}://{host}:{port}" if host else None
        self.headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/x-www-form-urlencoded"}
        self.session = requests.Session()
        self.session.verify = False
        self._live_mode: bool = None  # None = not yet tested

    def _test_connectivity(self) -> bool:
        """Test if Splunk REST API is reachable. Cached after first call."""
        if self._live_mode is not None:
            return self._live_mode
        if not self.host or not self.token:
            self._live_mode = False
            return False
        try:
            r = self.session.get(
                f"{self.base_url}/services",
                headers={"Authorization": f"Bearer {self.token}"},
                params={"output_mode": "json"},
                timeout=5
            )
            self._live_mode = r.status_code in (200, 401, 403)
            if not self._live_mode:
                logger.warning("[Splunk] REST API unreachable — switching to DEMO MODE")
        except Exception:
            self._live_mode = False
            logger.warning("[Splunk] REST API unreachable — switching to DEMO MODE")
        return self._live_mode

    def run_search(self, spl: str, max_results: int = 50, earliest: str = "-1h", latest: str = "now") -> Dict:
        """Run a Splunk search. Falls back to demo mode if Splunk is unreachable."""
        if not self._test_connectivity():
            logger.info("[Splunk] DEMO MODE: returning simulated results")
            return _mock_results(spl, min(max_results, 15))
        try:
            job_resp = self.session.post(
                f"{self.base_url}/services/search/jobs",
                headers=self.headers,
                data={"search": f"search {spl}", "earliest_time": earliest,
                      "latest_time": latest, "output_mode": "json"},
                timeout=15
            )
            job_resp.raise_for_status()
            sid = job_resp.json()["sid"]
            logger.info(f"[Splunk] Search job created: {sid}")
            for _ in range(30):
                status_resp = self.session.get(
                    f"{self.base_url}/services/search/jobs/{sid}",
                    headers=self.headers, params={"output_mode": "json"}, timeout=10
                )
                state = status_resp.json()["entry"][0]["content"]["dispatchState"]
                if state in ("DONE", "FAILED"):
                    break
                time.sleep(2)
            results_resp = self.session.get(
                f"{self.base_url}/services/search/jobs/{sid}/results",
                headers=self.headers,
                params={"output_mode": "json", "count": max_results},
                timeout=15
            )
            results_resp.raise_for_status()
            data = results_resp.json()
            return {"spl": spl, "result_count": len(data.get("results", [])),
                    "results": data.get("results", [])[:max_results]}
        except Exception as e:
            logger.error(f"[Splunk] Live search failed: {str(e)} — returning demo results")
            return _mock_results(spl, 10)

    def list_saved_searches(self) -> list:
        """List saved searches. Returns mock data if Splunk unreachable."""
        if not self._test_connectivity():
            return [
                {"name": "MuleOps ADO Alert - Compliance Violations", "search": "index=muleops_ado severity=CRITICAL", "alert_type": "number of events"},
                {"name": "MuleOps ADO Alert - vCore Threshold", "search": "index=muleops_ado message=*vCore*", "alert_type": "number of events"},
                {"name": "MuleOps Error Rate Monitor", "search": "index=mule_apps level=ERROR | stats count by source", "alert_type": "always"},
                {"note": "DEMO MODE — showing sample saved searches"}
            ]
        try:
            r = self.session.get(f"{self.base_url}/services/saved/searches",
                                 headers=self.headers, params={"output_mode": "json", "count": 50}, timeout=10)
            r.raise_for_status()
            return [{"name": e["name"], "search": e["content"].get("search", ""),
                     "alert_type": e["content"].get("alert_type", "always")}
                    for e in r.json().get("entry", [])]
        except Exception as e:
            return [{"error": str(e)}]
