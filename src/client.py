"""Client interface for Antigravity LanguageServer gRPC-Web service."""

from typing import Any, Optional
import requests
import urllib3

from src.discovery import discover_endpoints
from src.models import LanguageServerEndpoint

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SERVICE_PATH = "exa.language_server_pb.LanguageServerService"


class LanguageServerClient:
    def __init__(self, endpoint: Optional[LanguageServerEndpoint] = None, target_app: Optional[str] = None):
        self.endpoint = endpoint
        self.target_app = target_app  # "antigravity-ide", "antigravity", or None for auto
        self._session = requests.Session()
        self._session.verify = False
        self._endpoints_by_app: dict[str, LanguageServerEndpoint] = {}

    def is_connected(self, app: Optional[str] = None) -> bool:
        if app in ("ide", "antigravity-ide"):
            ep = self._endpoints_by_app.get("antigravity-ide")
            return bool(ep and self._ping(ep.port, ep.csrf_token))
        if app in ("v2", "antigravity"):
            ep = self._endpoints_by_app.get("antigravity")
            return bool(ep and self._ping(ep.port, ep.csrf_token))

        if self.endpoint:
            return self._ping(self.endpoint.port, self.endpoint.csrf_token)
        return False

    def refresh_connection(self, target_app: Optional[str] = None) -> bool:
        """Scan and verify running LanguageServer instances for both IDE and 2.0."""
        target = target_app or self.target_app
        endpoints = discover_endpoints()
        self._endpoints_by_app.clear()

        for ep in endpoints:
            if self._ping(ep.port, ep.csrf_token):
                app_key = ep.app_data_dir or "antigravity-ide"
                # Store by exact app key
                if app_key not in self._endpoints_by_app:
                    self._endpoints_by_app[app_key] = ep

        # Pick primary active endpoint
        if target in ("antigravity-ide", "ide") and "antigravity-ide" in self._endpoints_by_app:
            self.endpoint = self._endpoints_by_app["antigravity-ide"]
        elif target in ("antigravity", "v2") and "antigravity" in self._endpoints_by_app:
            self.endpoint = self._endpoints_by_app["antigravity"]
        elif "antigravity-ide" in self._endpoints_by_app:
            self.endpoint = self._endpoints_by_app["antigravity-ide"]
        elif "antigravity" in self._endpoints_by_app:
            self.endpoint = self._endpoints_by_app["antigravity"]
        else:
            self.endpoint = None

        return bool(self._endpoints_by_app)

    def get_status(self) -> dict[str, Any]:
        ep_ide = self._endpoints_by_app.get("antigravity-ide")
        ep_v2 = self._endpoints_by_app.get("antigravity")
        ide_ok = bool(ep_ide and self._ping(ep_ide.port, ep_ide.csrf_token))
        v2_ok = bool(ep_v2 and self._ping(ep_v2.port, ep_v2.csrf_token))
        return {
            "ide": {"connected": ide_ok, "port": ep_ide.port if ep_ide else None},
            "v2": {"connected": v2_ok, "port": ep_v2.port if ep_v2 else None},
            "ide_connected": ide_ok,
            "v2_connected": v2_ok,
            "ide_port": ep_ide.port if ep_ide else None,
            "v2_port": ep_v2.port if ep_v2 else None,
        }

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

    def call(self, method: str, payload: Optional[dict[str, Any]] = None, timeout: int = 15, app: Optional[str] = None) -> Optional[dict[str, Any]]:
        target_ep = self.endpoint
        if app in ("ide", "antigravity-ide"):
            target_ep = self._endpoints_by_app.get("antigravity-ide")
        elif app in ("v2", "antigravity"):
            target_ep = self._endpoints_by_app.get("antigravity")

        if not target_ep:
            self.refresh_connection(app)
            target_ep = self.endpoint

        if not target_ep:
            return None

        url = f"https://127.0.0.1:{target_ep.port}/{SERVICE_PATH}/{method}"
        headers = {
            "Content-Type": "application/json",
            "Connect-Protocol-Version": "1",
            "X-Codeium-Csrf-Token": target_ep.csrf_token,
        }
        try:
            resp = self._session.post(url, headers=headers, json=payload or {}, timeout=timeout)
            if resp.status_code == 200:
                return resp.json()
        except requests.exceptions.RequestException:
            # Re-try once after refresh
            if self.refresh_connection(app):
                target_ep = self.endpoint
                if target_ep:
                    url = f"https://127.0.0.1:{target_ep.port}/{SERVICE_PATH}/{method}"
                    headers["X-Codeium-Csrf-Token"] = target_ep.csrf_token
                    try:
                        resp = self._session.post(url, headers=headers, json=payload or {}, timeout=timeout)
                        if resp.status_code == 200:
                            return resp.json()
                    except Exception:
                        pass
        return None

    def get_all_trajectories(self, app: Optional[str] = None) -> dict[str, Any]:
        """Returns trajectories from specified app or merges both with app tagging."""
        results: dict[str, Any] = {}

        apps_to_query = []
        if app in ("ide", "antigravity-ide"):
            apps_to_query = ["antigravity-ide"]
        elif app in ("v2", "antigravity"):
            apps_to_query = ["antigravity"]
        else:
            apps_to_query = ["antigravity-ide", "antigravity"]

        for a_key in apps_to_query:
            ep = self._endpoints_by_app.get(a_key)
            if not ep:
                continue
            data = self.call("GetAllCascadeTrajectories", payload={}, app=a_key)
            if data and isinstance(data, dict):
                trajs = data.get("trajectories", data.get("trajectorySummaries", {}))
                app_tag = "v2" if a_key == "antigravity" else "ide"
                for cid, item in trajs.items():
                    if isinstance(item, dict):
                        item_copy = dict(item)
                        item_copy["_app_target"] = app_tag
                        results[cid] = item_copy

        return results

    def get_trajectory(self, cascade_id: str, app: Optional[str] = None) -> Optional[dict[str, Any]]:
        # If app specified, check that one first
        if app:
            res = self.call("GetCascadeTrajectory", payload={"cascadeId": cascade_id}, app=app)
            if res and res.get("trajectory"):
                return res["trajectory"]

        # Otherwise check active endpoint, then fallback to other app
        res = self.call("GetCascadeTrajectory", payload={"cascadeId": cascade_id})
        if res and res.get("trajectory"):
            return res["trajectory"]

        for other_app in ("antigravity-ide", "antigravity"):
            res = self.call("GetCascadeTrajectory", payload={"cascadeId": cascade_id}, app=other_app)
            if res and res.get("trajectory"):
                return res["trajectory"]

        return None
