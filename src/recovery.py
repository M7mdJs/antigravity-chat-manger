from typing import Any, Callable, Optional

from src.client import LanguageServerClient
from src.storage import scan_disk_conversations


class RecoveryEngine:
    def __init__(self, client: LanguageServerClient):
        self.client = client

    def scan_unindexed(self, target_app: str = "both") -> dict[str, Any]:
        disk_items = scan_disk_conversations(app_filter=target_app)
        api_items = self.client.get_all_trajectories(app=target_app) if self.client.is_connected(app=target_app) else {}
        api_ids = set(api_items.keys())

        unindexed_ids = [cid for cid in disk_items.keys() if cid not in api_ids]

        return {
            "total_disk": len(disk_items),
            "total_api": len(api_items),
            "unindexed_count": len(unindexed_ids),
            "unindexed_ids": unindexed_ids,
            "connected": self.client.is_connected(app=target_app),
        }

    def run_recovery(
        self,
        target_app: str = "both",
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
    ) -> dict[str, Any]:
        if not self.client.is_connected(app=target_app) and not self.client.refresh_connection(target_app):
            return {
                "success": False,
                "error": "Antigravity LanguageServer is not running for the selected application.",
            }

        scan = self.scan_unindexed(target_app=target_app)
        unindexed_ids = scan["unindexed_ids"]

        activated = []
        failed = []

        total = len(unindexed_ids)
        for i, cid in enumerate(unindexed_ids):
            if progress_callback:
                progress_callback(cid, i + 1, total)

            traj = self.client.get_trajectory(cid, app=target_app)
            if traj and traj.get("steps"):
                activated.append(cid)
            else:
                failed.append(cid)

        return {
            "success": True,
            "total_scanned": total,
            "activated": activated,
            "failed": failed,
            "activated_count": len(activated),
            "failed_count": len(failed),
        }
