"""Entry point for Antigravity Chat Manager.

Supports native Desktop GUI (default), lightweight local web mode,
and terminal CLI commands.
"""

import argparse
import sys
from pathlib import Path

# Ensure root folder is in python path
sys.path.insert(0, str(Path(__file__).parent.resolve()))

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from src.client import LanguageServerClient
from src.exporter import export_database_file, export_html, export_json, export_markdown
from src.parser import parse_api_trajectory, parse_transcript_records
from src.recovery import RecoveryEngine
from src.storage import read_transcript_lines, scan_disk_conversations


def main():
    parser = argparse.ArgumentParser(
        description="Antigravity Chat Manager & History Hub",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="Launch as local browser-based GUI instead of native desktop window",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="CLI: List all conversations discovered on disk and via LanguageServer",
    )
    parser.add_argument(
        "--export",
        metavar="ID",
        nargs="?",
        const="ALL",
        help="CLI: Export conversation by ID (or 'ALL' for everything)",
    )
    parser.add_argument(
        "--format",
        choices=["md", "json", "html", "db", "pb"],
        default="md",
        help="Export format (md, json, html, db, pb). Default: md",
    )
    parser.add_argument(
        "--level",
        choices=["basic", "thinking", "full"],
        default="full",
        help="Export detail level (basic, thinking, full). Default: full",
    )
    parser.add_argument(
        "--out",
        default="./exports",
        help="Output directory for exports. Default: ./exports",
    )
    parser.add_argument(
        "--recover",
        action="store_true",
        help="CLI: Scan disk for unindexed sessions and reactivate them in LanguageServer",
    )

    args = parser.parse_args()

    # CLI command: List
    if args.list:
        _cli_list()
        return

    # CLI command: Recover
    if args.recover:
        _cli_recover()
        return

    # CLI command: Export
    if args.export:
        _cli_export(args.export, args.format, args.level, args.out)
        return

    # Web Mode
    if args.web:
        from src.app import run_gui
        run_gui()
        return

    # Default Mode: Native Desktop GUI
    from src.gui_app import start_gui
    start_gui()


def _cli_list():
    client = LanguageServerClient()
    connected = client.refresh_connection()
    disk_map = scan_disk_conversations()
    api_items = client.get_all_trajectories() if connected else {}

    print(f"\nDiscovered {len(disk_map)} conversations on disk | LanguageServer: {'ONLINE' if connected else 'OFFLINE'}\n")
    print(f"{'#':<4} {'Source':<8} {'Steps':<7} {'Last Modified':<20} {'ID':<12} {'Title'}")
    print("-" * 80)

    items = list(disk_map.values())
    for item in items:
        if item.id in api_items:
            item.source = "api"
            api_summary = api_items[item.id].get("summary")
            if api_summary:
                item.title = api_summary
    items.sort(key=lambda x: x.last_modified_time or "", reverse=True)

    for i, item in enumerate(items, 1):
        mtime = (item.last_modified_time or "")[:19]
        cid = item.id[:8] + "..."
        title = item.title[:35]
        print(f"{i:<4} {item.source.upper():<8} {item.step_count:<7} {mtime:<20} {cid:<12} {title}")
    print()


def _cli_recover():
    client = LanguageServerClient()
    if not client.refresh_connection():
        print("\n[!] Antigravity LanguageServer is not running. Please open Antigravity IDE first.\n")
        return

    engine = RecoveryEngine(client)
    print("\nScanning for unindexed conversations on disk...")

    def progress(cid, cur, total):
        print(f"[{cur}/{total}] Reactivating session {cid[:8]}...")

    res = engine.run_recovery(progress_callback=progress)
    if res.get("success"):
        print(f"\n[+] Recovery finished: {res.get('activated_count', 0)} sessions reactivated.\n")
    else:
        print(f"\n[-] Recovery failed: {res.get('error')}\n")


def _cli_export(target_id: str, fmt: str, level: str, out_dir: str):
    client = LanguageServerClient()
    client.refresh_connection()
    disk_map = scan_disk_conversations()

    dest = Path(out_dir)
    dest.mkdir(parents=True, exist_ok=True)

    targets = list(disk_map.keys()) if target_id == "ALL" else [target_id]

    print(f"\nExporting {len(targets)} session(s) to '{dest}' as {fmt.upper()} (level: {level})...\n")
    for cid in targets:
        summary = disk_map.get(cid)
        messages = []
        if client.is_connected():
            traj = client.get_trajectory(cid)
            if traj:
                messages = parse_api_trajectory(traj)
        if not messages:
            records = read_transcript_lines(cid)
            if records:
                messages = parse_transcript_records(records)

        clean_title = "".join(c for c in (summary.title if summary else cid) if c.isalnum() or c in (" ", "-", "_"))[:30].strip()
        stem = f"{clean_title}_{cid[:8]}" if clean_title else cid[:8]

        if fmt in ("db", "pb"):
            out_file = dest / f"{stem}.{fmt}"
            if summary:
                res = export_database_file(summary, out_file, fmt=fmt)
                if res.get("success"):
                    print(f"  -> {out_file.name} ({res.get('size', 0)} bytes)")
                else:
                    print(f"  -> [!] Failed {cid[:8]}: {res.get('error')}")
            else:
                print(f"  -> [!] Session {cid[:8]} not found in disk registry.")
        elif fmt == "json":
            out_file = dest / f"{stem}.json"
            out_file.write_text(export_json(summary, messages), encoding="utf-8")
            print(f"  -> {out_file.name}")
        elif fmt == "html":
            out_file = dest / f"{stem}.html"
            out_file.write_text(export_html(summary, messages, level=level), encoding="utf-8")
            print(f"  -> {out_file.name}")
        else:
            out_file = dest / f"{stem}.md"
            out_file.write_text(export_markdown(summary, messages, level=level), encoding="utf-8")
            print(f"  -> {out_file.name}")
    print("\n[+] Export completed.\n")


if __name__ == "__main__":
    main()
