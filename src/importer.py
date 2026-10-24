from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import sqlite3
from typing import Any, Optional
import uuid

from src.client import LanguageServerClient
from src.storage import BASE_DIR_IDE, BASE_DIR_V2, get_app_target_dir


def _cleanup_source_wal_files(source_path: Path):
    for extra in ("-wal", "-shm"):
        aux = source_path.with_name(source_path.name + extra)
        if aux.exists():
            try:
                aux.unlink()
            except Exception:
                pass


def _extract_text_and_title_from_db(db_path: Path) -> tuple[str, list[dict[str, Any]]]:
    title = ""
    lines = []
    try:
        con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=3)
        rows = con.execute("SELECT idx, step_type, step_payload FROM steps ORDER BY idx ASC").fetchall()
        for idx, stype, payload in rows:
            if not payload:
                continue
            rec_type = "USER_INPUT" if stype == 14 else "PLANNER_RESPONSE"
            strings = []
            for m in re.finditer(rb"[\x20-\x7e\xd8-\xdf\xe0-\xef]{3,}", payload):
                try:
                    s = m.group(0).decode("utf-8").strip()
                    if s and not s.startswith("MODEL_") and not s.startswith("API_"):
                        strings.append(s)
                except Exception:
                    pass
            content = " ".join(strings[:4]) if strings else ""
            if content and not title and rec_type == "USER_INPUT":
                title = content[:60]
            if content:
                lines.append({
                    "type": rec_type,
                    "content": content,
                    "step_index": idx,
                })
        con.close()
    except Exception:
        pass
    return title, lines


def import_database_file(
    source_path: Path,
    client: Optional[LanguageServerClient] = None,
    target_app: str = "ide",
) -> dict[str, Any]:
    if not source_path.is_file():
        return {"success": False, "error": f"File not found: {source_path}"}

    ext = source_path.suffix.lower()
    if ext not in (".db", ".pb"):
        return {"success": False, "error": "Only .db or .pb conversation files are supported."}

    if ext == ".db":
        try:
            src_chk = sqlite3.connect(source_path.as_posix())
            src_chk.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            src_chk.execute("PRAGMA journal_mode=DELETE;")
            src_chk.commit()
            src_chk.close()
        except Exception:
            pass
        _cleanup_source_wal_files(source_path)

    cid = source_path.stem
    detected_title = ""
    step_count = 0

    if ext == ".db":
        try:
            con = sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True)
            row = con.execute("SELECT cascade_id FROM trajectory_meta LIMIT 1").fetchone()
            if row and row[0]:
                cid = str(row[0]).strip()
            row_count = con.execute("SELECT COUNT(*) FROM steps").fetchone()
            step_count = row_count[0] if row_count else 0
            con.close()
        except Exception:
            pass
        detected_title, _ = _extract_text_and_title_from_db(source_path)

    targets: list[tuple[Path, Path, str]] = []
    if target_app in ("ide", "both"):
        targets.append((
            get_app_target_dir("ide", "conversations"),
            get_app_target_dir("ide", "brain") / cid,
            "ide",
        ))
    if target_app in ("v2", "both"):
        targets.append((
            get_app_target_dir("v2", "conversations"),
            get_app_target_dir("v2", "brain") / cid,
            "v2",
        ))

    copied_destinations = []

    for conv_dir, brain_dir, app_tag in targets:
        dest_file = conv_dir / f"{cid}{ext}"
        try:
            if ext == ".db":
                src_con = sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True)
                dst_con = sqlite3.connect(dest_file.as_posix())
                with dst_con:
                    src_con.backup(dst_con)
                dst_con.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                dst_con.execute("PRAGMA journal_mode=WAL;")
                dst_con.commit()
                dst_con.close()
                src_con.close()
            else:
                shutil.copy2(source_path, dest_file)

            copied_destinations.append(str(dest_file))

            logs_dir = brain_dir / ".system_generated" / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            transcript_file = logs_dir / "transcript.jsonl"

            if not transcript_file.exists():
                _, lines = _extract_text_and_title_from_db(dest_file)
                if lines:
                    records = [json.dumps(l, ensure_ascii=False) for l in lines]
                    transcript_file.write_text("\n".join(records) + "\n", encoding="utf-8")

            if app_tag == "v2":
                _register_v2_summary(cid, detected_title or f"Session {cid[:8]}", step_count)

        except Exception as e:
            _cleanup_source_wal_files(source_path)
            return {"success": False, "error": f"Failed importing to {conv_dir.name}: {e}"}

    _cleanup_source_wal_files(source_path)

    ls_client = client or LanguageServerClient()
    connected = ls_client.is_connected() or ls_client.refresh_connection()
    activated = False
    if connected:
        for _, _, app_tag in targets:
            traj = ls_client.get_trajectory(cid, app=app_tag)
            if traj and traj.get("steps"):
                activated = True
        ls_client.get_all_trajectories()

    target_desc = "Antigravity IDE & 2.0" if target_app == "both" else ("Antigravity 2.0" if target_app == "v2" else "Antigravity IDE")
    msg_status = "and reloaded." if activated else "to storage."

    return {
        "success": True,
        "id": cid,
        "destination": copied_destinations[0] if copied_destinations else "",
        "activated_in_ls": activated,
        "message": f"Imported session {cid[:8]} into {target_desc} {msg_status}",
    }


def import_json_export(
    source_path: Path,
    target_app: str = "ide",
) -> dict[str, Any]:
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

    targets: list[tuple[Path, Path, str]] = []
    if target_app in ("ide", "both"):
        targets.append((
            get_app_target_dir("ide", "conversations"),
            get_app_target_dir("ide", "brain") / cid,
            "ide",
        ))
    if target_app in ("v2", "both"):
        targets.append((
            get_app_target_dir("v2", "conversations"),
            get_app_target_dir("v2", "brain") / cid,
            "v2",
        ))

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

    transcript_content = "\n".join(lines) + "\n"

    try:
        for conv_dir, brain_dir, app_tag in targets:
            logs_dir = brain_dir / ".system_generated" / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            (logs_dir / "transcript.jsonl").write_text(transcript_content, encoding="utf-8")

            db_file = conv_dir / f"{cid}.db"
            if not db_file.exists():
                _create_minimal_conversation_db(db_file, cid, title, len(messages))

            if app_tag == "v2":
                _register_v2_summary(cid, title, len(messages))

        target_desc = "Antigravity IDE & 2.0" if target_app == "both" else ("Antigravity 2.0" if target_app == "v2" else "Antigravity IDE")
        return {
            "success": True,
            "id": cid,
            "title": title,
            "message": f"Imported {len(messages)} messages into {target_desc} session {cid[:8]}.",
        }
    except Exception as e:
        return {"success": False, "error": f"Failed writing imported session: {e}"}


def _create_minimal_conversation_db(db_path: Path, cid: str, title: str, step_count: int):
    try:
        con = sqlite3.connect(db_path.as_posix())
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("CREATE TABLE IF NOT EXISTS trajectory_meta (trajectory_id text, cascade_id text, trajectory_type integer, source integer, PRIMARY KEY (trajectory_id));")
        con.execute("CREATE TABLE IF NOT EXISTS steps (idx integer, step_type integer NOT NULL DEFAULT 0, status integer NOT NULL DEFAULT 0, has_subtrajectory numeric NOT NULL DEFAULT false, metadata blob, error_details blob, permissions blob, task_details blob, render_info blob, step_payload blob, step_format integer NOT NULL DEFAULT 0, PRIMARY KEY (idx));")
        con.execute("CREATE TABLE IF NOT EXISTS gen_metadata (idx integer, data blob, size integer NOT NULL DEFAULT 0, PRIMARY KEY (idx));")
        con.execute("CREATE TABLE IF NOT EXISTS executor_metadata (idx integer, data blob, PRIMARY KEY (idx));")
        con.execute("CREATE TABLE IF NOT EXISTS parent_references (idx integer, data blob, PRIMARY KEY (idx));")
        con.execute("CREATE TABLE IF NOT EXISTS trajectory_metadata_blob (id text DEFAULT 'main', data blob, PRIMARY KEY (id));")
        con.execute("CREATE TABLE IF NOT EXISTS battle_mode_infos (idx integer, data blob, PRIMARY KEY (idx));")

        tid = str(uuid.uuid4())
        con.execute("INSERT OR REPLACE INTO trajectory_meta VALUES (?, ?, 4, 1);", (tid, cid))
        con.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        con.commit()
        con.close()
    except Exception:
        pass


def _register_v2_summary(cid: str, title: str, step_count: int):
    db_path = BASE_DIR_V2 / "conversation_summaries.db"
    if not db_path.exists():
        return
    try:
        con = sqlite3.connect(db_path.as_posix())
        mtime = datetime.now(timezone.utc).isoformat()
        con.execute("""
            INSERT OR REPLACE INTO conversation_summaries
            (conversation_id, title, preview, step_count, last_modified_time, workspace_uris, app_data_dir)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (cid, title, title, step_count, mtime, "", "antigravity"))
        con.commit()
        con.close()
    except Exception:
        pass
