"""Client interface for Antigravity LanguageServer gRPC-Web service."""

from typing import Any, Optional
import requests
import urllib3

from src.discovery import discover_endpoints
from src.models import LanguageServerEndpoint

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SERVICE_PATH = "exa.language_server_pb.LanguageServerService"


class LanguageServerClient:
    def __init__(self, endpoint: Optional[LanguageServerEndpoint] = None):
        self.endpoint = endpoint
        self._session = requests.Session()
        self._session.verify = False

    def is_connected(self) -> bool:
        if not self.endpoint:
            return False
        return self._ping(self.endpoint.port, self.endpoint.csrf_token)

    def refresh_connection(self) -> bool:
        endpoints = discover_endpoints()
        for ep in endpoints:
            if self._ping(ep.port, ep.csrf_token):
                self.endpoint = ep
                return True
        self.endpoint = None
        return False

    def _ping(self, port: int, csrf: str) -> bool:
        url = f"https://127.0.0.1:{port}/{SERVICE_PATH}/GetAllCascadeTrajectories"
        headers = {
            "Content-Type": "application/json",
            "Connect-Protocol-Version": "1",
            "X-Codeium-Csrf-Token": csrf,
        }
        try:
            resp = self._session.post(url, headers=headers, json={}, timeout=2.5)
            return resp.status_code == 200
        except Exception:
            return False

    def call(self, method: str, payload: Optional[dict[str, Any]] = None, timeout: int = 15) -> Optional[dict[str, Any]]:
        if not self.endpoint and not self.refresh_connection():
            return None

        url = f"https://127.0.0.1:{self.endpoint.port}/{SERVICE_PATH}/{method}"
        headers = {
            "Content-Type": "application/json",
            "Connect-Protocol-Version": "1",
            "X-Codeium-Csrf-Token": self.endpoint.csrf_token,
        }
        try:
            resp = self._session.post(url, headers=headers, json=payload or {}, timeout=timeout)
            if resp.status_code == 200:
                return resp.json()
        except requests.exceptions.RequestException:
            # Re-try once after refreshing endpoint in case port or CSRF changed on reload
            if self.refresh_connection():
                url = f"https://127.0.0.1:{self.endpoint.port}/{SERVICE_PATH}/{method}"
                headers["X-Codeium-Csrf-Token"] = self.endpoint.csrf_token
                try:
                    resp = self._session.post(url, headers=headers, json=payload or {}, timeout=timeout)
                    if resp.status_code == 200:
                        return resp.json()
                except Exception:
                    pass
        return None

    def get_all_trajectories(self) -> dict[str, Any]:
        result = self.call("GetAllCascadeTrajectories", payload={})
        if not result or not isinstance(result, dict):
            return {}
        return result.get("trajectories", result.get("trajectorySummaries", {}))

    def get_trajectory(self, cascade_id: str) -> Optional[dict[str, Any]]:
        result = self.call("GetCascadeTrajectory", payload={"cascadeId": cascade_id})
        if not result or not isinstance(result, dict):
            return None
        return result.get("trajectory")
