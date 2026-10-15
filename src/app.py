"""Desktop application launcher and window manager."""

import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser

from src.server import ChatManagerServer


def find_free_port(start_port: int = 8765) -> int:
    for port in range(start_port, start_port + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return start_port


def launch_browser_app(url: str):
    # Try Edge in App mode (native-like window on Windows)
    if sys.platform == "win32":
        edge_paths = [
            os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        ]
        for path in edge_paths:
            if os.path.isfile(path):
                try:
                    subprocess.Popen([path, f"--app={url}"])
                    return
                except Exception:
                    break

        chrome_paths = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        ]
        for path in chrome_paths:
            if os.path.isfile(path):
                try:
                    subprocess.Popen([path, f"--app={url}"])
                    return
                except Exception:
                    break

    # Standard browser fallback
    webbrowser.open(url)


def run_gui(host: str = "127.0.0.1", port: int = 8765):
    actual_port = find_free_port(port)
    server = ChatManagerServer(host=host, port=actual_port)

    server_thread = threading.Thread(target=server.start, daemon=True)
    server_thread.start()

    url = f"http://{host}:{actual_port}"
    print(f"\n==========================================")
    print(f" Antigravity Chat Manager & History Hub")
    print(f" Web GUI running at: {url}")
    print(f" Press Ctrl+C in terminal to stop.")
    print(f"==========================================\n")

    # Launch desktop window
    launch_browser_app(url)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down server...")
        server.stop()
