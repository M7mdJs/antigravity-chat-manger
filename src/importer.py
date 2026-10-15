"""Import utility for restoring conversation databases and transcripts."""

import json
from pathlib import Path
import shutil
import sqlite3
import uuid
from typing import Any, Optional

from src.client import LanguageServerClient
from src.storage import get_conversations_dirs


def import_database_file(source_path: Path, client: Optional[LanguageServerClient] = None) -> dict[str, Any]:
    if not source_path.is_file():
        return {"success": False, "error": f"File not found: {source_path}"}

    ext = source_path.suffix.lower()
    if ext not in (".db", ".pb"):
        return {"success": False, "error": "Only .db or .pb conversation files are supported for database import."}

    # Extract or infer cascade ID
    cid = source_path.stem
    if ext == ".db":
        try:
            con = sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True)
            row = con.execute("SELECT cascade_id FROM trajectory_meta LIMIT 1").fetchone()
            if row and row[0]:
                cid = str(row[0]).strip()
            con.close()
        except Exception:
            pass

    target_dirs = get_conversations_dirs()
    if not target_dirs:
        home_target = Path.home() / ".gemini" / "antigravity-ide" / "conversations"
        home_target.mkdir(parents=True, exist_ok=True)
        target_dirs = [home_target]

    copied_paths = []
    for dest_dir in target_dirs:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_file = dest_dir / f"{cid}{ext}"
        try:
            if ext == ".db":
                src_con = sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True)
                dst_con = sqlite3.connect(dest_file.as_posix())
                with dst_con:
                    src_con.backup(dst_con)
                dst_con.close()
                src_con.close()
            else:
                shutil.copy2(source_path, dest_file)
            copied_paths.append(str(dest_file))
        except Exception as e:
            return {"success": False, "error": f"Failed copying file to {dest_file}: {e}"}

    # Also prepare the brain directory for artifacts and transcript
    brain_dir = Path.home() / ".gemini" / "antigravity-ide" / "brain" / cid
    (brain_dir / ".system_generated" / "logs").mkdir(parents=True, exist_ok=True)

    # Trigger LanguageServer indexation if alive
    ls_client = client or LanguageServerClient()
    connected = ls_client.is_connected() or ls_client.refresh_connection()
    activated = False
    if connected:
        traj = ls_client.get_trajectory(cid)
        activated = bool(traj and traj.get("steps"))
        ls_client.get_all_trajectories()

    msg_status = "and loaded into live LanguageServer memory." if activated else "to Antigravity storage. Open or reload Antigravity IDE to view it."
    return {
        "success": True,
        "id": cid,
        "destination": copied_paths[0] if copied_paths else "",
        "activated_in_ls": activated,
        "message": f"Successfully imported session {cid[:8]} {msg_status}",
    }


def import_json_export(source_path: Path) -> dict[str, Any]:
    if not source_path.is_file():
        return {"success": False, "error": f"File not found: {source_path}"}

    try:
        content = source_path.read_text(encoding="utf-8")
        data = json.loads(content)
    except Exception as e:
        return {"success": False, "error": f"Invalid JSON file: {e}"}

    cid = data.get("id") or str(uuid.uuid4())
    title = data.get("title") or "Imported Session"
    messages = data.get("messages", [])

    archive_dir = Path.home() / ".gemini" / "antigravity-ide" / "brain" / cid / ".system_generated" / "logs"
    archive_dir.mkdir(parents=True, exist_ok=True)
    transcript_file = archive_dir / "transcript.jsonl"

    lines = []
    for m in messages:
        rec_type = "USER_INPUT" if m.get("role") == "user" else "PLANNER_RESPONSE"
        lines.append(json.dumps({
            "type": rec_type,
            "content": m.get("content", ""),
            "timestamp": m.get("timestamp"),
            "thinking": m.get("thinking"),
            "tool_calls": [
                {
                    "name": t.get("name", "tool"),
                    "arguments": t.get("input", {}),
                    "summary": t.get("summary"),
                }
                for t in m.get("tools", [])
            ],
        }, ensure_ascii=False))

    try:
        transcript_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return {
            "success": True,
            "id": cid,
            "title": title,
            "message": f"Imported {len(messages)} messages from JSON export into session {cid[:8]}.",
        }
    except Exception as e:
        return {"success": False, "error": f"Failed writing transcript: {e}"}
