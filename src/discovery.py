"""LanguageServer process discovery module.

Auto-detects running Antigravity LanguageServer processes, extracts CSRF tokens,
and verifies listening ports across Windows, macOS, and Linux.
"""

import json
import os
import platform
import re
import subprocess
from typing import Optional

from src.models import LanguageServerEndpoint


def _run_cmd(cmd: list[str], timeout: int = 10) -> str:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        return proc.stdout.strip()
    except Exception:
        return ""


def find_windows_listening_ports(pid: int) -> list[int]:
    ps_cmd = f"Get-NetTCPConnection -OwningProcess {pid} -State Listen | Select-Object -ExpandProperty LocalPort"
    out = _run_cmd(["powershell", "-NoProfile", "-Command", ps_cmd], timeout=8)
    ports = []
    for line in out.splitlines():
        line = line.strip()
        if line.isdigit():
            port = int(line)
            if port not in ports:
                ports.append(port)
    if ports:
        return ports

    netstat_out = _run_cmd(["netstat", "-ano"], timeout=8)
    for line in netstat_out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[1].upper() == "TCP" and parts[3].upper() == "LISTENING":
            if parts[4] == str(pid):
                addr = parts[2]
                if ":" in addr:
                    try:
                        p = int(addr.rsplit(":", 1)[1])
                        if p not in ports:
                            ports.append(p)
                    except ValueError:
                        continue
    return ports


def discover_endpoints() -> list[LanguageServerEndpoint]:
    system = platform.system()
    candidates = []

    if system == "Windows":
        candidates = _discover_windows()
    elif system == "Darwin":
        candidates = _discover_macos()
    elif system == "Linux":
        candidates = _discover_linux()

    return candidates


def _discover_windows() -> list[LanguageServerEndpoint]:
    ps_query = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -like '*language_server*' } | "
        "Select-Object ProcessId, CommandLine | "
        "ConvertTo-Json -Compress"
    )
    raw = _run_cmd(["powershell", "-NoProfile", "-Command", ps_query], timeout=15)
    if not raw:
        return []

    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            data = [data]
    except Exception:
        return []

    endpoints = []
    for item in data:
        pid = item.get("ProcessId")
        cmd = item.get("CommandLine") or ""
        if not pid or not cmd:
            continue

        csrf_match = re.search(r"--csrf_token\s+([a-zA-Z0-9_\-]+)", cmd)
        csrf = csrf_match.group(1) if csrf_match else ""
        if not csrf:
            continue

        port_match = re.search(r"--https_server_port\s+(\d+)", cmd)
        ws_match = re.search(r"--workspace_id\s+(\S+)", cmd)
        app_match = re.search(r"--app_data_dir\s+(\S+)", cmd)

        explicit_port = int(port_match.group(1)) if port_match else None
        ports_to_try = [explicit_port] if explicit_port else find_windows_listening_ports(pid)

        for port in ports_to_try:
            if port and port > 0:
                endpoints.append(
                    LanguageServerEndpoint(
                        pid=pid,
                        port=port,
                        csrf_token=csrf,
                        workspace_id=ws_match.group(1) if ws_match else None,
                        app_data_dir=app_match.group(1) if app_match else None,
                    )
                )

    return endpoints


def _discover_macos() -> list[LanguageServerEndpoint]:
    out = _run_cmd(["pgrep", "-fl", "language_server"], timeout=8)
    endpoints = []
    for line in out.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) < 2:
            continue
        pid_str, cmd = parts[0], parts[1]
        try:
            pid = int(pid_str)
        except ValueError:
            continue

        csrf_match = re.search(r"--csrf_token\s+([a-zA-Z0-9_\-]+)", cmd)
        port_match = re.search(r"--https_server_port\s+(\d+)", cmd)
        if not csrf_match:
            continue

        csrf = csrf_match.group(1)
        if port_match:
            endpoints.append(
                LanguageServerEndpoint(
                    pid=pid,
                    port=int(port_match.group(1)),
                    csrf_token=csrf,
                )
            )
    return endpoints


def _discover_linux() -> list[LanguageServerEndpoint]:
    out = _run_cmd(["pgrep", "-fl", "language_server"], timeout=8)
    endpoints = []
    for line in out.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) < 2:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        cmd = parts[1]
        csrf_match = re.search(r"--csrf_token\s+([a-zA-Z0-9_\-]+)", cmd)
        port_match = re.search(r"--https_server_port\s+(\d+)", cmd)
        if csrf_match and port_match:
            endpoints.append(
                LanguageServerEndpoint(
                    pid=pid,
                    port=int(port_match.group(1)),
                    csrf_token=csrf_match.group(1),
                )
            )
    return endpoints
