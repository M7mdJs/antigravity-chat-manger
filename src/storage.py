"""Local storage inspector and offline conversation reader for Antigravity (IDE & 2.0)."""

import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import urllib.parse
from typing import Any, Optional

from src.models import ConversationSummary

BASE_DIR_IDE = Path.home() / ".gemini" / "antigravity-ide"
BASE_DIR_V2 = Path.home() / ".gemini" / "antigravity"


def get_app_dirs() -> list[tuple[Path, str]]:
    """Returns list of (base_path, app_tag) for installed Antigravity versions."""
    res: list[tuple[Path, str]] = []
    if BASE_DIR_IDE.exists() and BASE_DIR_IDE.is_dir():
        res.append((BASE_DIR_IDE, "ide"))
    if BASE_DIR_V2.exists() and BASE_DIR_V2.is_dir():
        res.append((BASE_DIR_V2, "v2"))
    return res


def get_base_dirs() -> list[Path]:
    return [p for p, _ in get_app_dirs()]


def get_conversations_dirs() -> list[Path]:
    dirs = []
    for base, _ in get_app_dirs():
        p = base / "conversations"
        if p.exists() and p.is_dir():
            dirs.append(p)
    return dirs


def get_brain_dirs() -> list[Path]:
    dirs = []
    for base, _ in get_app_dirs():
        p = base / "brain"
        if p.exists() and p.is_dir():
            dirs.append(p)
    return dirs


def get_app_target_dir(app_tag: str, subfolder: str = "conversations") -> Path:
    base = BASE_DIR_V2 if app_tag in ("v2", "antigravity", "2.0") else BASE_DIR_IDE
    p = base / subfolder
    p.mkdir(parents=True, exist_ok=True)
    return p


def extract_vscdb_titles() -> dict[str, dict[str, str]]:
    """Extract titles for Antigravity IDE from globalStorage state.vscdb."""
    db_path = Path.home() / "AppData" / "Roaming" / "Antigravity IDE" / "User" / "globalStorage" / "state.vscdb"
    if not db_path.is_file():
        return {}

    metadata: dict[str, dict[str, str]] = {}
    try:
        con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=3)
        row = con.execute("SELECT value FROM ItemTable WHERE key='antigravityUnifiedStateSync.trajectorySummaries'").fetchone()
        con.close()
        if not row or not row[0]:
            return metadata

        raw = base64.b64decode(row[0])
        uuid_matches = list(re.finditer(rb"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", raw))

        for i in range(len(uuid_matches)):
            start = uuid_matches[i].start()
            end = uuid_matches[i + 1].start() if i + 1 < len(uuid_matches) else len(raw)
            chunk = raw[start:end]
            cid = uuid_matches[i].group(0).decode("ascii")

            title = None
            b64s = re.findall(rb"[A-Za-z0-9+/]{12,}={0,2}", chunk)
            for b in b64s:
                try:
                    d = base64.b64decode(b)
                    if len(d) > 2 and d[0] == 0x0A:
                        length = d[1]
                        candidate = d[2 : 2 + length].decode("utf-8").strip()
                        if candidate and not candidate.startswith("file:/") and not candidate.startswith("http"):
                            title = candidate
                            break
                except Exception:
                    pass

            if title:
                metadata[cid] = {"title": title}
    except Exception:
        pass

    return metadata


def extract_v2_summaries() -> dict[str, dict[str, Any]]:
    """Extract titles and summaries for Antigravity 2.0 from conversation_summaries.db."""
    db_path = BASE_DIR_V2 / "conversation_summaries.db"
    if not db_path.is_file():
        return {}

    metadata: dict[str, dict[str, Any]] = {}
    try:
        con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=3)
        cur = con.cursor()
        for row in cur.execute("SELECT conversation_id, title, preview, step_count, last_modified_time FROM conversation_summaries"):
            cid, title, preview, steps, mtime = row
            if cid:
                metadata[cid] = {
                    "title": title,
                    "preview": preview,
                    "step_count": steps,
                    "last_modified_time": mtime,
                }
        con.close()
    except Exception:
        pass

    return metadata


def read_workspace_from_db(db_path: Path) -> Optional[str]:
    try:
        con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=2)
        row = con.execute("SELECT data FROM trajectory_metadata_blob LIMIT 1").fetchone()
        con.close()
        if row and row[0]:
            m = re.search(rb"file:///[^\x00-\x1f\x7f]+", row[0])
            if m:
                ws = m.group(0).decode("utf-8", "ignore")
                return urllib.parse.unquote(ws).replace("file:///", "").replace("%20", " ")
    except Exception:
        pass
    return None


def read_step_count_and_prompt_from_db(db_path: Path) -> tuple[int, Optional[str]]:
    step_count = 0
    prompt = None
    try:
        con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=2)
        row_count = con.execute("SELECT COUNT(*) FROM steps").fetchone()
        step_count = row_count[0] if row_count else 0

        # Try to find user prompt
        row_user = con.execute("SELECT step_payload FROM steps WHERE step_type = 14 ORDER BY idx ASC LIMIT 1").fetchone()
        if row_user and row_user[0]:
            strings = re.findall(rb"[\x20-\x7e\xd8-\xdf\xe0-\xef]{3,}", row_user[0])
            for s in strings:
                try:
                    txt = s.decode("utf-8").strip()
                    if txt and not txt.startswith("MODEL_") and not txt.startswith("API_") and not txt.startswith("$") and not txt.startswith("b$") and len(txt) > 2:
                        prompt = txt[:80]
                        break
                except Exception:
                    pass
        con.close()
    except Exception:
        pass
    return step_count, prompt


def scan_disk_conversations(app_filter: Optional[str] = None) -> dict[str, ConversationSummary]:
    results: dict[str, ConversationSummary] = {}
    vscdb_titles = extract_vscdb_titles()
    v2_summaries = extract_v2_summaries()

    # Scan conversation files (.db / .pb) across both app directories
    for base_dir, app_tag in get_app_dirs():
        if app_filter and app_filter != "all":
            if app_filter == "ide" and app_tag != "ide":
                continue
            if app_filter in ("v2", "2.0") and app_tag != "v2":
                continue

        conv_dir = base_dir / "conversations"
        if not conv_dir.is_dir():
            continue

        try:
            for entry in os.scandir(conv_dir):
                if not entry.is_file():
                    continue
                name = entry.name
                if name.endswith((".db", ".pb")) and not name.endswith(("-shm", "-wal")):
                    cid = name.rsplit(".", 1)[0]
                    mtime = datetime.fromtimestamp(entry.stat().st_mtime, tz=timezone.utc).isoformat()
                    p = Path(entry.path)

                    ws = read_workspace_from_db(p) if name.endswith(".db") else None
                    steps, prompt_text = read_step_count_and_prompt_from_db(p) if name.endswith(".db") else (0, None)

                    known_title = None
                    if app_tag == "v2" and cid in v2_summaries:
                        known_title = v2_summaries[cid].get("title")
                    elif cid in vscdb_titles:
                        known_title = vscdb_titles[cid].get("title")

                    title = known_title or prompt_text or f"Session {cid[:8]}"
                    preview = prompt_text or (ws if ws else "")

                    if cid in results:
                        results[cid].app_target = "both"
                    else:
                        results[cid] = ConversationSummary(
                            id=cid,
                            title=title,
                            preview=preview,
                            step_count=steps,
                            last_modified_time=mtime,
                            workspace=ws,
                            source="disk",
                            app_target=app_tag,
                        )
        except OSError:
            continue

    # Augment details from brain transcripts
    for base_dir, app_tag in get_app_dirs():
        if app_filter and app_filter != "all":
            if app_filter == "ide" and app_tag != "ide":
                continue
            if app_filter in ("v2", "2.0") and app_tag != "v2":
                continue

        brain_dir = base_dir / "brain"
        if not brain_dir.is_dir():
            continue

        try:
            for item in os.scandir(brain_dir):
                if not item.is_dir():
                    continue
                cid = item.name
                log_file = Path(item.path) / ".system_generated" / "logs" / "transcript.jsonl"
                if not log_file.is_file():
                    continue

                first_input, first_ts, last_ts, total_steps = _extract_transcript_meta(log_file)
                known_title = None
                if app_tag == "v2" and cid in v2_summaries:
                    known_title = v2_summaries[cid].get("title")
                elif cid in vscdb_titles:
                    known_title = vscdb_titles[cid].get("title")

                if cid not in results:
                    title = known_title or first_input or f"Session {cid[:8]}"
                    results[cid] = ConversationSummary(
                        id=cid,
                        title=title,
                        preview=first_input or "",
                        step_count=total_steps,
                        created_time=first_ts,
                        last_modified_time=last_ts,
                        source="disk",
                        app_target=app_tag,
                    )
                else:
                    item_summary = results[cid]
                    if total_steps > item_summary.step_count:
                        item_summary.step_count = total_steps
                    if first_ts and not item_summary.created_time:
                        item_summary.created_time = first_ts
                    if last_ts and (not item_summary.last_modified_time or last_ts > item_summary.last_modified_time):
                        item_summary.last_modified_time = last_ts
                    if not item_summary.title or item_summary.title.startswith("Session "):
                        if known_title:
                            item_summary.title = known_title
                        elif first_input:
                            item_summary.title = first_input
        except OSError:
            continue

    return results


def _extract_transcript_meta(path: Path) -> tuple[str, Optional[str], Optional[str], int]:
    first_input = ""
    first_ts = None
    last_ts = None
    count = 0

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                count += 1
                try:
                    obj = json.loads(line)
                    ts = obj.get("timestamp")
                    if ts:
                        if not first_ts:
                            first_ts = ts
                        last_ts = ts

                    if not first_input and obj.get("type") == "USER_INPUT":
                        content = obj.get("content", "").strip()
                        if content:
                            clean_prompt = content.splitlines()[0][:90].strip()
                            clean_prompt = clean_prompt.replace("<USER_REQUEST>", "").replace("</USER_REQUEST>", "").strip()
                            first_input = clean_prompt
                except json.JSONDecodeError:
                    continue
    except Exception:
        pass

    return first_input, first_ts, last_ts, count


def read_transcript_lines(cascade_id: str, app_target: Optional[str] = None) -> list[dict[str, Any]]:
    app_dirs = get_app_dirs()
    if app_target in ("ide", "antigravity-ide"):
        app_dirs = [(BASE_DIR_IDE, "ide")]
    elif app_target in ("v2", "antigravity"):
        app_dirs = [(BASE_DIR_V2, "v2")]

    for base_dir, _ in app_dirs:
        brain_dir = base_dir / "brain"
        log_file = brain_dir / cascade_id / ".system_generated" / "logs" / "transcript_full.jsonl"
        if not log_file.is_file():
            log_file = brain_dir / cascade_id / ".system_generated" / "logs" / "transcript.jsonl"
        if log_file.is_file():
            records = []
            try:
                with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                records.append(json.loads(line))
                            except json.JSONDecodeError:
                                pass
                return records
            except Exception:
                continue
    return []
