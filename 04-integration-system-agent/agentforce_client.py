"""
Salesforce Agentforce Client
Handles OAuth token acquisition (JWT Bearer flow preferred, Client Credentials fallback)
and Agent API session management.

JWT Bearer Flow is required to obtain JWT-format access tokens for the Agent API.
Set SF_PRIVATE_KEY_PATH and SF_RUN_AS_USER to enable JWT Bearer mode.
"""
import requests
import logging
import uuid
import time
from typing import Optional

logger = logging.getLogger(__name__)


class AgentforceClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        instance_url: str,
        agent_id: str,
        api_base_url: str = "https://api.salesforce.com",
        private_key_path: Optional[str] = None,
        run_as_user: Optional[str] = None,
    ):
        if not all([client_id, instance_url, agent_id]):
            raise ValueError("SF_CLIENT_ID, SF_INSTANCE_URL, SF_AGENT_ID are required")
        self.client_id = client_id
        self.client_secret = client_secret
        self.instance_url = instance_url.rstrip("/")
        self.agent_id = agent_id
        self.api_base_url = api_base_url.rstrip("/")
        self.private_key_path = private_key_path
        self.run_as_user = run_as_user
        self._access_token: Optional[str] = None
        self._session_id: Optional[str] = None
        self._sequence_id: int = 1
        mode = "JWT Bearer" if (private_key_path and run_as_user) else "Client Credentials"
        logger.info(f"[Agentforce] Initialized with {mode} auth, api_base={self.api_base_url}")

    # ------------------------------------------------------------------ #
    # Token acquisition
    # ------------------------------------------------------------------ #

    def _get_token_jwt_bearer(self) -> str:
        """Obtain a JWT-format access token via JWT Bearer Flow."""
        try:
            import jwt as pyjwt
            from cryptography.hazmat.primitives.serialization import load_pem_private_key
        except ImportError:
            raise ImportError(
                "PyJWT and cryptography packages are required for JWT Bearer flow. "
                "Run: pip3 install PyJWT cryptography"
            )

        with open(self.private_key_path, "rb") as f:
            private_key = load_pem_private_key(f.read(), password=None)

        now = int(time.time())
        payload = {
            "iss": self.client_id,
            "sub": self.run_as_user,
            "aud": "https://login.salesforce.com",
            "exp": now + 300,
        }
        signed_jwt = pyjwt.encode(payload, private_key, algorithm="RS256")

        r = requests.post(
            f"{self.instance_url}/services/oauth2/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": signed_jwt,
            },
            timeout=15,
        )
        if not r.ok:
            logger.error(f"[Agentforce] JWT Bearer token failed {r.status_code}: {r.text[:400]}")
        r.raise_for_status()
        self._access_token = r.json()["access_token"]
        is_jwt = self._access_token.startswith("eyJ")
        logger.info(
            f"[Agentforce] JWT Bearer token acquired (len={len(self._access_token)}, "
            f"prefix={self._access_token[:6]}, is_jwt={is_jwt})"
        )
        return self._access_token

    def _get_token_client_credentials(self) -> str:
        """Obtain access token via Client Credentials flow (fallback)."""
        r = requests.post(
            f"{self.instance_url}/services/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            timeout=15,
        )
        r.raise_for_status()
        self._access_token = r.json()["access_token"]
        is_jwt = self._access_token.startswith("eyJ")
        logger.info(
            f"[Agentforce] Client Credentials token acquired (len={len(self._access_token)}, "
            f"prefix={self._access_token[:6]}, is_jwt={is_jwt})"
        )
        return self._access_token

    def _get_token(self) -> str:
        """Get token: JWT Bearer if key is configured, else Client Credentials."""
        if self.private_key_path and self.run_as_user:
            return self._get_token_jwt_bearer()
        return self._get_token_client_credentials()

    # ------------------------------------------------------------------ #
    # URL helpers
    # ------------------------------------------------------------------ #

    def _agent_api_url(self, suffix: str) -> str:
        """URL for agent-scoped endpoints (session creation)."""
        return f"{self.api_base_url}/einstein/ai-agent/v1/agents/{self.agent_id}{suffix}"

    def _session_api_url(self, session_id: str, suffix: str = "") -> str:
        """URL for session-scoped endpoints (messages, end-session).
        Per Salesforce API docs: POST /sessions/{id}/messages  (no agent ID prefix)
        """
        return f"{self.api_base_url}/einstein/ai-agent/v1/sessions/{session_id}{suffix}"

    # ------------------------------------------------------------------ #
    # Session management
    # ------------------------------------------------------------------ #

    def _create_session(self, initiated_by: Optional[str] = None) -> str:
        """Create an Agentforce session.

        When ``initiated_by`` is supplied (the Slack user ID from the OBO token),
        it is embedded into ``externalSessionKey`` as ``slack-<user>-<uuid>`` so
        that Salesforce audit logs can be correlated back to the originating human.
        """
        token = self._access_token or self._get_token()
        if initiated_by:
            ext_key = f"slack-{initiated_by}-{uuid.uuid4()}"
        else:
            ext_key = str(uuid.uuid4())
        session_body = {
            "externalSessionKey": ext_key,
            "instanceConfig": {"endpoint": self.instance_url},
            "bypassUser": True,
        }
        r = requests.post(
            self._agent_api_url("/sessions"),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=session_body,
            timeout=15,
        )
        if r.status_code == 401:
            token = self._get_token()
            if initiated_by:
                session_body["externalSessionKey"] = f"slack-{initiated_by}-{uuid.uuid4()}"
            else:
                session_body["externalSessionKey"] = str(uuid.uuid4())
            r = requests.post(
                self._agent_api_url("/sessions"),
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=session_body,
                timeout=15,
            )
        if not r.ok:
            logger.error(f"[Agentforce] Session creation failed {r.status_code}: {r.text[:500]}")
        r.raise_for_status()
        self._session_id = r.json()["sessionId"]
        logger.info(
            f"[Agentforce] Session created: {self._session_id}"
            + (f" | OBO user: {initiated_by}" if initiated_by else "")
        )
        return self._session_id

    # ------------------------------------------------------------------ #
    # Message sending
    # ------------------------------------------------------------------ #

    def send_message(self, message: str, initiated_by: Optional[str] = None) -> str:
        """Send a message to the Agentforce agent and return the text response.

        Args:
            message:      Natural-language query to send.
            initiated_by: Slack user ID from the OBO token (``X-Initiated-By``).
                          When provided it is embedded into the Agentforce
                          ``externalSessionKey`` for end-to-end audit traceability.
        """
        token = self._access_token or self._get_token()
        session_id = self._session_id or self._create_session(initiated_by=initiated_by)

        # Messages endpoint: /einstein/ai-agent/v1/sessions/{sessionId}/messages
        # (does NOT include agent ID - per official Salesforce API spec)
        r = requests.post(
            self._session_api_url(session_id, "/messages"),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"message": {"type": "Text", "sequenceId": self._sequence_id, "text": message}},
            timeout=60,
        )
        if r.status_code in (401, 404):
            # Token or session expired — refresh both
            token = self._get_token()
            session_id = self._create_session(initiated_by=initiated_by)
            r = requests.post(
                self._session_api_url(session_id, "/messages"),
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"message": {"type": "Text", "sequenceId": self._sequence_id, "text": message}},
                timeout=60,
            )
        r.raise_for_status()
        data = r.json()
        self._sequence_id += 1

        # Extract text from Salesforce Agent API response
        # Official response format: {"messages": [{"type": "Inform", "message": "...", ...}]}
        messages = data.get("messages", []) if isinstance(data, dict) else []
        for msg in messages:
            if msg.get("type") in ("Inform", "Text") and msg.get("message"):
                return msg["message"]
            for part in msg.get("content", []):
                if part.get("type") == "text" and part.get("text"):
                    return part["text"]

        # Fallback for legacy A2A format
        if isinstance(data, dict):
            result = data.get("result")
            if isinstance(result, dict):
                for artifact in result.get("artifacts", []):
                    for part in artifact.get("parts", []):
                        if part.get("type") == "text" and part.get("text"):
                            return part["text"]

        logger.warning(f"[Agentforce] Unexpected response format: {str(data)[:300]}")
        return "No response received from Agentforce agent"