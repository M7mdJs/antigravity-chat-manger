from datetime import datetime
import html
import json
from pathlib import Path
import shutil
import sqlite3
from typing import Any, Optional

from src.models import ConversationMessage, ConversationSummary
from src.storage import get_base_dirs, get_conversations_dirs


def export_markdown(summary: ConversationSummary, messages: list[ConversationMessage], level: str = "full") -> str:
    lines = [
        f"# {summary.title}",
        "",
        f"- **Session ID**: `{summary.id}`",
        f"- **Steps**: {summary.step_count}",
        f"- **Last Modified**: {summary.last_modified_time or 'N/A'}",
        f"- **Workspace**: {summary.workspace or 'N/A'}",
        f"- **Exported At**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "---",
        "",
    ]

    for msg in messages:
        ts = f" *({msg.timestamp[:19]})*" if msg.timestamp else ""
        if msg.role == "user":
            lines.append(f"## 🧑 User{ts}\n")
            lines.append(msg.content.strip())
            lines.append("\n---\n")

        elif msg.role == "assistant":
            model_badge = f" `[{msg.model}]`" if msg.model else ""
            lines.append(f"## 🤖 Assistant{model_badge}{ts}\n")

            if level in ("thinking", "full") and msg.thinking:
                dur = f" ({msg.thinking_duration})" if msg.thinking_duration else ""
                lines.append(f"<details><summary>🧠 <b>Thinking Process{dur}</b></summary>\n")
                lines.append(msg.thinking.strip())
                lines.append("\n</details>\n")

            if msg.content:
                lines.append(msg.content.strip())
                lines.append("")

            if level == "full" and msg.tools:
                lines.append("### 🛠️ Actions & Tools\n")
                for t in msg.tools:
                    if t.name == "run_command":
                        cmd = t.input_data.get("command", "")
                        lines.append(f"**Command executed**:`\n```bash\n{cmd}\n```")
                        if t.output_data:
                            lines.append(f"Output (exit {t.exit_code if t.exit_code is not None else 0}):\n```\n{t.output_data.strip()}\n```\n")
                    elif t.diff:
                        lines.append(f"**Code change**: `{t.input_data.get('file', 'file')}`\n```diff\n{t.diff.strip()}\n```\n")
                    elif t.summary:
                        lines.append(f"- **{t.name}**: {t.summary}")
                lines.append("")

            lines.append("\n---\n")

    return "\n".join(lines)


def export_json(summary: ConversationSummary, messages: list[ConversationMessage]) -> str:
    data = {
        "id": summary.id,
        "title": summary.title,
        "step_count": summary.step_count,
        "created_time": summary.created_time,
        "last_modified_time": summary.last_modified_time,
        "workspace": summary.workspace,
        "messages": [
            {
                "role": m.role,
                "content": m.content,
                "timestamp": m.timestamp,
                "model": m.model,
                "thinking": m.thinking,
                "thinking_duration": m.thinking_duration,
                "tools": [
                    {
                        "name": t.name,
                        "action": t.action_type,
                        "input": t.input_data,
                        "output": t.output_data,
                        "exit_code": t.exit_code,
                        "diff": t.diff,
                        "summary": t.summary,
                    }
                    for t in m.tools
                ],
            }
            for m in messages
        ],
    }
    return json.dumps(data, indent=2, ensure_ascii=False)


def export_html(summary: ConversationSummary, messages: list[ConversationMessage], level: str = "full") -> str:
    safe_title = html.escape(summary.title)
    body_items = []

    for msg in messages:
        ts = f"<span class='ts'>{html.escape(msg.timestamp[:19])}</span>" if msg.timestamp else ""
        if msg.role == "user":
            body_items.append(
                f"<div class='msg user'>"
                f"<div class='msg-hdr'><strong>🧑 User</strong>{ts}</div>"
                f"<div class='msg-body'><pre class='text-content'>{html.escape(msg.content)}</pre></div>"
                f"</div>"
            )
        elif msg.role == "assistant":
            model = f"<span class='badge'>{html.escape(msg.model)}</span>" if msg.model else ""
            thinking_html = ""
            if level in ("thinking", "full") and msg.thinking:
                dur = f" ({html.escape(msg.thinking_duration)})" if msg.thinking_duration else ""
                thinking_html = (
                    f"<details class='thinking-box'>"
                    f"<summary>🧠 Reasoning Chain{dur}</summary>"
                    f"<div class='thinking-content'>{html.escape(msg.thinking)}</div>"
                    f"</details>"
                )

            tools_html = ""
            if level == "full" and msg.tools:
                tools_list = []
                for t in msg.tools:
                    if t.name == "run_command":
                        cmd = html.escape(t.input_data.get("command", ""))
                        out = html.escape(t.output_data or "")
                        tools_list.append(
                            f"<div class='tool-card'><strong>Terminal:</strong> <code>{cmd}</code>"
                            f"<pre class='tool-out'>{out}</pre></div>"
                        )
                    elif t.diff:
                        tools_list.append(
                            f"<div class='tool-card'><strong>Diff ({html.escape(t.input_data.get('file', ''))}):</strong>"
                            f"<pre class='diff-view'>{html.escape(t.diff)}</pre></div>"
                        )
                    elif t.summary:
                        tools_list.append(f"<div class='tool-card'><strong>{html.escape(t.name)}:</strong> {html.escape(t.summary)}</div>")
                if tools_list:
                    tools_html = "<div class='tools-box'>" + "".join(tools_list) + "</div>"

            content_html = f"<div class='msg-body'><pre class='text-content'>{html.escape(msg.content)}</pre></div>" if msg.content else ""
            body_items.append(
                f"<div class='msg assistant'>"
                f"<div class='msg-hdr'><strong>🤖 Assistant</strong>{model}{ts}</div>"
                f"{thinking_html}"
                f"{content_html}"
                f"{tools_html}"
                f"</div>"
            )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{safe_title}</title>
<style>
  :root {{ --bg: #090d16; --surface: #131c2e; --border: #233554; --text: #e2e8f0; --accent: #38bdf8; }}
  body {{ background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 2rem; display: flex; justify-content: center; }}
  .container {{ max-width: 900px; width: 100%; }}
  .header {{ padding-bottom: 1.5rem; border-bottom: 1px solid var(--border); margin-bottom: 2rem; }}
  h1 {{ margin: 0 0 0.5rem 0; font-size: 1.8rem; color: #f8fafc; }}
  .meta {{ color: #94a3b8; font-size: 0.9rem; display: flex; gap: 1.5rem; flex-wrap: wrap; }}
  .msg {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 1.2rem; margin-bottom: 1.5rem; }}
  .msg.user {{ border-left: 4px solid #3b82f6; }}
  .msg.assistant {{ border-left: 4px solid #10b981; }}
  .msg-hdr {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.8rem; }}
  .ts {{ font-size: 0.8rem; color: #64748b; font-family: monospace; }}
  .badge {{ background: #1e293b; color: #38bdf8; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; margin-left: 8px; }}
  pre.text-content {{ white-space: pre-wrap; word-wrap: break-word; font-family: inherit; margin: 0; }}
  .thinking-box {{ background: #0f172a; border: 1px dashed #334155; border-radius: 6px; padding: 0.7rem; margin-bottom: 1rem; color: #cbd5e1; font-size: 0.9rem; }}
  .thinking-box summary {{ cursor: pointer; color: #a78bfa; font-weight: 600; outline: none; }}
  .thinking-content {{ margin-top: 0.8rem; white-space: pre-wrap; font-family: monospace; font-size: 0.85rem; color: #94a3b8; }}
  .tools-box {{ margin-top: 1rem; display: flex; flex-direction: column; gap: 0.6rem; }}
  .tool-card {{ background: #0b1120; border: 1px solid #1e293b; border-radius: 6px; padding: 0.6rem 0.8rem; font-size: 0.85rem; }}
  .tool-out, .diff-view {{ background: #020617; padding: 0.5rem; border-radius: 4px; margin-top: 0.4rem; font-family: monospace; font-size: 0.8rem; overflow-x: auto; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>{safe_title}</h1>
    <div class="meta">
      <span><b>ID:</b> {summary.id}</span>
      <span><b>Steps:</b> {summary.step_count}</span>
      <span><b>Workspace:</b> {summary.workspace or 'Default'}</span>
    </div>
  </div>
  {"".join(body_items)}
</div>
</body>
</html>"""


def export_database_file(summary: ConversationSummary, dest_path: Path, fmt: str = "db") -> dict[str, Any]:
    src_file: Optional[Path] = None
    for cdir in get_conversations_dirs():
        candidate_db = cdir / f"{summary.id}.db"
        candidate_pb = cdir / f"{summary.id}.pb"
        if fmt == "pb" and candidate_pb.is_file():
            src_file = candidate_pb
            break
        elif candidate_db.is_file():
            src_file = candidate_db
            break
        elif candidate_pb.is_file():
            src_file = candidate_pb
            break

    if not src_file:
        for base in get_base_dirs():
            candidate = base / "implicit" / f"{summary.id}.pb"
            if candidate.is_file():
                src_file = candidate
                break

    if not src_file or not src_file.is_file():
        return {
            "success": False,
            "error": f"No native conversation file found on disk for session {summary.id[:8]}.",
        }

    dest_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        if src_file.suffix.lower() == ".db" and dest_path.suffix.lower() == ".db":
            src_con = sqlite3.connect(f"file:{src_file.as_posix()}?mode=ro", uri=True)
            dst_con = sqlite3.connect(dest_path.as_posix())
            with dst_con:
                src_con.backup(dst_con)
            dst_con.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            dst_con.execute("PRAGMA journal_mode=DELETE;")
            dst_con.commit()
            dst_con.close()
            src_con.close()

            for extra in ("-wal", "-shm"):
                aux = dest_path.with_name(dest_path.name + extra)
                if aux.exists():
                    try:
                        aux.unlink()
                    except Exception:
                        pass
        else:
            shutil.copy2(src_file, dest_path)

        return {
            "success": True,
            "path": str(dest_path),
            "size": dest_path.stat().st_size,
            "format": dest_path.suffix.lower().lstrip("."),
        }
    except Exception as e:
        return {"success": False, "error": f"Database export failed: {e}"}
