"""Conversation recovery engine.

Detects unindexed or orphaned conversations on disk and reactivates them
in the Antigravity LanguageServer using on-demand trajectory loading.
"""

from typing import Any, Callable, Optional

from src.client import LanguageServerClient
from src.models import ConversationSummary
from src.storage import scan_disk_conversations


class RecoveryEngine:
    def __init__(self, client: LanguageServerClient):
        self.client = client

    def scan_unindexed(self) -> dict[str, Any]:
        disk_items = scan_disk_conversations()
        api_items = self.client.get_all_trajectories() if self.client.is_connected() else {}
        api_ids = set(api_items.keys())

        unindexed_ids = [cid for cid in disk_items.keys() if cid not in api_ids]

        return {
            "total_disk": len(disk_items),
            "total_api": len(api_items),
            "unindexed_count": len(unindexed_ids),
            "unindexed_ids": unindexed_ids,
            "connected": self.client.is_connected(),
        }

    def run_recovery(
        self,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
    ) -> dict[str, Any]:
        if not self.client.is_connected() and not self.client.refresh_connection():
            return {
                "success": False,
                "error": "Antigravity LanguageServer is not running. Please open Antigravity IDE with at least one workspace to run recovery.",
            }

        scan = self.scan_unindexed()
        unindexed_ids = scan["unindexed_ids"]

        activated = []
        failed = []

        total = len(unindexed_ids)
        for i, cid in enumerate(unindexed_ids):
            if progress_callback:
                progress_callback(cid, i + 1, total)

            # Trigger on-demand load via GetCascadeTrajectory
            traj = self.client.get_trajectory(cid)
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
