"""Embedded HTTP server and REST API for Antigravity Chat Manager."""

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from src.client import LanguageServerClient
from src.exporter import export_html, export_json, export_markdown
from src.parser import parse_api_trajectory, parse_transcript_records
from src.recovery import RecoveryEngine
from src.storage import read_transcript_lines, scan_disk_conversations


class ChatManagerServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 8765, web_dir: Optional[Path] = None):
        self.host = host
        self.port = port
        self.web_dir = web_dir or (Path(__file__).parent.parent / "web")
        self.client = LanguageServerClient()
        self.client.refresh_connection()
        self.recovery = RecoveryEngine(self.client)
        self.httpd: Optional[ThreadingHTTPServer] = None

    def create_handler(self):
        server_instance = self

        class APIRequestHandler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(server_instance.web_dir), **kwargs)

            def do_GET(self):
                parsed = urlparse(self.path)
                path = parsed.path.rstrip("/")
                query = parse_qs(parsed.query)

                if path == "/api/status":
                    self._handle_status()
                elif path == "/api/conversations":
                    self._handle_conversations(query)
                elif path.startswith("/api/conversations/"):
                    cid = path.split("/api/conversations/")[1]
                    self._handle_conversation_detail(cid)
                elif path == "/api/analytics":
                    self._handle_analytics()
                else:
                    # Fallback to static web files
                    if path == "" or path == "/":
                        self.path = "/index.html"
                    super().do_GET()

            def do_POST(self):
                parsed = urlparse(self.path)
                path = parsed.path.rstrip("/")

                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
                try:
                    payload = json.loads(body)
                except json.JSONDecodeError:
                    payload = {}

                if path == "/api/export":
                    self._handle_export(payload)
                elif path == "/api/recover":
                    self._handle_recover()
                elif path == "/api/refresh":
                    server_instance.client.refresh_connection()
                    self._send_json({"connected": server_instance.client.is_connected()})
                else:
                    self.send_error(404, "Endpoint not found")

            def _send_json(self, data: Any, status: int = 200):
                resp = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(resp)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(resp)

            def _handle_status(self):
                connected = server_instance.client.is_connected()
                ep = server_instance.client.endpoint
                self._send_json({
                    "connected": connected,
                    "endpoint": {
                        "port": ep.port if ep else None,
                        "pid": ep.pid if ep else None,
                        "workspace": ep.workspace_id if ep else None,
                    } if ep else None,
                })

            def _handle_conversations(self, query: dict[str, list[str]]):
                search_q = query.get("q", [""])[0].lower().strip()
                filter_src = query.get("source", ["all"])[0].lower()

                # Get disk conversations
                disk_map = scan_disk_conversations()

                # Get API active conversations
                api_items = server_instance.client.get_all_trajectories() if server_instance.client.is_connected() else {}

                merged = dict(disk_map)
                for cid, api_info in api_items.items():
                    if cid in merged:
                        merged[cid].source = "api"
                        if api_info.get("summary"):
                            merged[cid].title = api_info["summary"]
                            merged[cid].preview = api_info["summary"]
                        if api_info.get("stepCount"):
                            merged[cid].step_count = api_info["stepCount"]
                        if api_info.get("lastModifiedTime"):
                            merged[cid].last_modified_time = api_info["lastModifiedTime"]
                    else:
                        merged[cid] = ConversationSummary(
                            id=cid,
                            title=api_info.get("summary") or f"Session {cid[:8]}",
                            preview=api_info.get("summary") or "",
                            step_count=api_info.get("stepCount", 0),
                            last_modified_time=api_info.get("lastModifiedTime"),
                            source="api",
                        )

                items = list(merged.values())

                # Filter by source
                if filter_src == "api":
                    items = [x for x in items if x.source == "api"]
                elif filter_src == "disk":
                    items = [x for x in items if x.source == "disk"]

                # Filter by search
                if search_q:
                    items = [
                        x for x in items
                        if search_q in x.title.lower()
                        or search_q in x.id.lower()
                        or search_q in (x.preview or "").lower()
                    ]

                # Sort by last_modified_time descending
                items.sort(key=lambda x: x.last_modified_time or "", reverse=True)

                self._send_json([
                    {
                        "id": x.id,
                        "title": x.title,
                        "preview": x.preview,
                        "step_count": x.step_count,
                        "created_time": x.created_time,
                        "last_modified_time": x.last_modified_time,
                        "workspace": x.workspace,
                        "source": x.source,
                    }
                    for x in items
                ])

            def _handle_conversation_detail(self, cascade_id: str):
                disk_map = scan_disk_conversations()
                summary = disk_map.get(cascade_id)

                # Try via LanguageServer first
                messages = []
                if server_instance.client.is_connected() or server_instance.client.refresh_connection():
                    traj = server_instance.client.get_trajectory(cascade_id)
                    if traj:
                        messages = parse_api_trajectory(traj)

                # Fallback to offline transcripts if API is unavailable or empty
                if not messages:
                    records = read_transcript_lines(cascade_id)
                    if records:
                        messages = parse_transcript_records(records)

                if not summary:
                    summary = ConversationSummary(
                        id=cascade_id,
                        title=f"Session {cascade_id[:8]}",
                        preview="",
                        step_count=len(messages),
                    )

                self._send_json({
                    "id": summary.id,
                    "title": summary.title,
                    "preview": summary.preview,
                    "step_count": summary.step_count or len(messages),
                    "created_time": summary.created_time,
                    "last_modified_time": summary.last_modified_time,
                    "workspace": summary.workspace,
                    "source": summary.source,
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
                })

            def _handle_export(self, payload: dict[str, Any]):
                ids = payload.get("ids", [])
                fmt = payload.get("format", "md").lower()
                level = payload.get("level", "full").lower()
                out_dir_str = payload.get("output_dir", "./exports")

                out_dir = Path(out_dir_str)
                out_dir.mkdir(parents=True, exist_ok=True)

                disk_map = scan_disk_conversations()
                exported_files = []

                for cid in ids:
                    summary = disk_map.get(cid) or ConversationSummary(id=cid, title=cid[:8], preview="", step_count=0)
                    messages = []
                    if server_instance.client.is_connected():
                        traj = server_instance.client.get_trajectory(cid)
                        if traj:
                            messages = parse_api_trajectory(traj)
                    if not messages:
                        records = read_transcript_lines(cid)
                        if records:
                            messages = parse_transcript_records(records)

                    clean_title = "".join(c for c in summary.title if c.isalnum() or c in (" ", "-", "_"))[:40].strip()
                    file_stem = f"{clean_title}_{cid[:8]}" if clean_title else cid[:8]

                    if fmt == "json":
                        content = export_json(summary, messages)
                        fpath = out_dir / f"{file_stem}.json"
                    elif fmt == "html":
                        content = export_html(summary, messages, level=level)
                        fpath = out_dir / f"{file_stem}.html"
                    else:
                        content = export_markdown(summary, messages, level=level)
                        fpath = out_dir / f"{file_stem}.md"

                    fpath.write_text(content, encoding="utf-8")
                    exported_files.append(str(fpath.resolve()))

                self._send_json({
                    "success": True,
                    "count": len(exported_files),
                    "files": exported_files,
                })

            def _handle_recover(self):
                res = server_instance.recovery.run_recovery()
                self._send_json(res)

            def _handle_analytics(self):
                disk_map = scan_disk_conversations()
                total_steps = sum(x.step_count for x in disk_map.values())
                workspaces = {}
                for x in disk_map.values():
                    ws = x.workspace or "Default Workspace"
                    workspaces[ws] = workspaces.get(ws, 0) + 1

                self._send_json({
                    "total_conversations": len(disk_map),
                    "total_steps": total_steps,
                    "connected_ls": server_instance.client.is_connected(),
                    "workspaces": workspaces,
                })

        return APIRequestHandler

    def start(self):
        handler_cls = self.create_handler()
        self.httpd = ThreadingHTTPServer((self.host, self.port), handler_cls)
        self.httpd.serve_forever()

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
