<div align="center">
  <h1>antigravity-chat-manger</h1>
  <p>Browse, export, and recover conversation sessions from Google Antigravity IDE.</p>

  <img src="https://img.shields.io/badge/python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-27272a?style=flat-square" alt="Platform">
  <img src="https://img.shields.io/badge/license-MIT-22c55e?style=flat-square" alt="License">
  <img src="https://img.shields.io/badge/UI-CustomTkinter-5e6ad2?style=flat-square" alt="UI">

  <br><br>

  <img src="https://img.shields.io/github/stars/M7mdJs/antigravity-chat-manger?style=flat-square&color=27272a" alt="Stars">
  <img src="https://img.shields.io/github/forks/M7mdJs/antigravity-chat-manger?style=flat-square&color=27272a" alt="Forks">
  <img src="https://img.shields.io/github/last-commit/M7mdJs/antigravity-chat-manger?style=flat-square&color=27272a" alt="Last Commit">
</div>

---

Antigravity stores all session data locally in SQLite databases, protobuf files, and JSONL transcripts, but gives you no built-in way to browse or manage that history outside the active editor window.

This tool fills that gap. Runs as a standalone desktop app or CLI utility. Reads sessions directly from disk and can connect to the running Antigravity LanguageServer over its local gRPC-Web endpoint for live indexing and session reactivation.

---

## Features

**Session browser** - full message threads across all workspaces, with model tags, timestamps, reasoning traces, terminal outputs, and file diffs.

**Export** - any session to `.db` (native SQLite backup), `.pb` (protobuf), Markdown, JSON, or HTML.

**Import and reactivation** - drop a `.db` or `.pb` file from a backup or another machine. If the IDE is open, the session loads into live memory immediately via LanguageServer.

**Crash recovery** - scans local storage for orphaned or unindexed sessions after an unexpected shutdown and reactivates them.

**Arabic text** - proper right-to-left rendering using arabic-reshaper and python-bidi across titles, prompts, reasoning blocks, and the markdown viewer.

**Progressive rendering** - long sessions (100+ steps) load in chunks. The UI never freezes.

---

## Installation

Requires **Python 3.10+**.

```bash
git clone https://github.com/M7mdJs/antigravity-chat-manger.git
cd antigravity-chat-manger
pip install -r requirements.txt
```

**Windows:**
```bash
run.bat
```

**Or directly:**
```bash
python main.py
```

---

## CLI

```bash
# List all sessions on disk and in the running LanguageServer
python main.py --list

# Recover orphaned sessions and reload them into Antigravity
python main.py --recover

# Export a session as a SQLite database
python main.py --export <SESSION_ID> --format db --out ./exports

# Export a session to Markdown
python main.py --export <SESSION_ID> --format md --out ./exports

# Export everything to HTML
python main.py --export ALL --format html --out ./exports
```

| Flag | Description | Default |
|------|-------------|---------|
| `--list` | Print all discovered sessions | - |
| `--recover` | Reactivate unindexed sessions into LanguageServer | - |
| `--export [ID]` | Session ID to export, or `ALL` | - |
| `--format` | `db` `pb` `md` `json` `html` | `md` |
| `--level` | Detail level: `basic` `thinking` `full` | `full` |
| `--out` | Output directory | `./exports` |

---

## How it works

Antigravity stores session data under `~/.gemini/antigravity-ide/`:

| Path | Contents |
|------|----------|
| `conversations/<id>.db` | SQLite - trajectory metadata, steps, tool payloads, diffs |
| `brain/<id>/.system_generated/logs/transcript.jsonl` | Full JSONL event stream of the conversation |
| `globalStorage/state.vscdb` | VSCode state DB - session title summaries |

When the IDE is running, it spawns `language_server_windows_x64.exe` on a dynamic local port with a CSRF token. The client discovers the process, reads the port and token from its arguments, and communicates with `LanguageServerService` using the Connect protocol over HTTP.

---

## Project structure

```
antigravity-chat-manger/
    src/
        gui_app.py        - CustomTkinter desktop UI
        markdown_view.py  - Markdown renderer with Arabic BiDi
        client.py         - LanguageServer Connect-protocol client
        discovery.py      - Process and port discovery
        storage.py        - SQLite and JSONL readers
        parser.py         - Trajectory and transcript parsers
        recovery.py       - Session recovery and reactivation
        importer.py       - Import engine for .db .pb .json
        exporter.py       - Export engine for all formats
        arabic.py         - Arabic reshaper and BiDi wrapper
        models.py         - Dataclasses and shared types
    main.py               - CLI and GUI entrypoint
    run.bat               - Windows launcher
    requirements.txt
    LICENSE
```

---

## License

MIT. See [LICENSE](LICENSE).

---

<div align="center">
  <sub>Built by <a href="https://github.com/M7mdJs">M7mdJs</a></sub>
</div>
