"""Native Desktop GUI for Antigravity Chat Manager.

Linear / Cursor-inspired design system — zinc-dark palette:
- Canvas:  #09090b  |  Sidebar: #111114  |  Active row: #1c1c22
- Accent:  #5e6ad2  |  Text: #f4f4f5 / #a1a1aa / #71717a
- Fast progressive chunked rendering (no UI freeze on long chats)
- Universal mouse-wheel scrolling without focus clicks
- Rich Markdown view with Arabic BiDi shaping
- Collapsible AI reasoning blocks
"""

import json
from pathlib import Path
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Any, Optional

import customtkinter as ctk

from src.arabic import fix_arabic
from src.client import LanguageServerClient
from src.exporter import export_database_file, export_html, export_json, export_markdown
from src.importer import import_database_file, import_json_export
from src.markdown_view import MarkdownViewer
from src.models import ConversationMessage, ConversationSummary
from src.parser import parse_api_trajectory, parse_transcript_records
from src.recovery import RecoveryEngine
from src.storage import read_transcript_lines, scan_disk_conversations

# ── Design tokens — Linear / Cursor zinc-dark ──────────────────────────────
THEMES = {
    "dark": {
        "name": "dark",
        # Surfaces
        "bg_window":         "#09090b",
        "bg_sidebar":        "#111114",
        "bg_row_hover":      "#17171c",
        "bg_row_active":     "#1c1c22",
        "bg_card":           "#18181b",
        "bg_card_hover":     "#1f1f26",
        "bg_elevated":       "#141417",
        "bg_input":          "#18181b",
        # Borders
        "border_sidebar":    "#1f1f24",
        "border_subtle":     "#27272a",
        "border_card":       "#27272a",
        # Accent
        "accent":            "#5e6ad2",
        "accent_hover":      "#7170ff",
        "accent_dim":        "#2d3068",
        # Text
        "text_primary":      "#f4f4f5",
        "text_secondary":    "#a1a1aa",
        "text_muted":        "#71717a",
        "text_faint":        "#3f3f46",
        # Buttons ghost style
        "btn_ghost_text":    "#a1a1aa",
        "btn_ghost_hover":   "#27272a",
        "btn_secondary":     "#18181b",
        "btn_secondary_hover": "#27272a",
        "btn_secondary_border": "#3f3f46",
        "btn_secondary_text": "#a1a1aa",
        # Message bubbles
        "user_bubble":       "#0d1829",
        "user_bubble_border": "#1e3a6e",
        # Reasoning / thinking
        "thinking_bg":       "#0f0f12",
        "thinking_border":   "#27272a",
        # Tools
        "tool_bg":           "#0d0d10",
        "tool_border":       "#27272a",
        # Status
        "status_green":      "#22c55e",
        "status_amber":      "#f59e0b",
        "status_error":      "#ef4444",
        "status_blue":       "#3b82f6",
        # Input
        "input_border":      "#27272a",
        # Filter pills
        "seg_active_bg":     "#1c1c22",
    },
}


class AntigravityGUI(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.current_theme_name = "dark"
        self.theme = THEMES[self.current_theme_name]
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")

        self.title("Antigravity Chat Manager")
        self.geometry("1300x860")
        self.minsize(980, 640)
        self.configure(fg_color=self.theme["bg_window"])

        self.client = LanguageServerClient()
        self.client.refresh_connection()
        self.recovery_engine = RecoveryEngine(self.client)

        self.conversations: list[ConversationSummary] = []
        self.active_id: Optional[str] = None
        self.active_summary: Optional[ConversationSummary] = None
        self.active_messages: list[ConversationMessage] = []
        self.current_filter = "All"
        self.search_query = ""
        self.current_tab = "Chat View"
        self.md_view_enabled = True

        self.CHUNK_SIZE = 12
        self.rendered_count = 0
        self._is_loading_chunk = False
        self._scroll_timer: Optional[str] = None
        self.load_more_frame: Optional[ctk.CTkFrame] = None

        self._build_layout()
        self._bind_smooth_scrolling()
        self._refresh_all()

    # ── Layout ────────────────────────────────────────────────────────────

    def _build_layout(self):
        self.grid_columnconfigure(0, weight=0, minsize=280)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        t = self.theme
        self._build_sidebar(t)
        self._build_main_panel(t)

    def _build_sidebar(self, t: dict):
        self.sidebar_frame = ctk.CTkFrame(self, width=280, corner_radius=0,
                                          fg_color=t["bg_sidebar"], border_width=0)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.sidebar_frame.grid_propagate(False)
        self.sidebar_frame.grid_columnconfigure(0, weight=1)
        self.sidebar_frame.grid_rowconfigure(4, weight=1)

        # Hairline right border
        tk.Frame(self.sidebar_frame, width=1, bg=t["border_sidebar"]).place(
            relx=1.0, rely=0.0, relheight=1.0, anchor="ne")

        # Brand header
        brand_row = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        brand_row.grid(row=0, column=0, padx=16, pady=(16, 0), sticky="ew")

        logo_dot = ctk.CTkFrame(brand_row, width=8, height=8, corner_radius=4,
                                 fg_color=t["accent"], border_width=0)
        logo_dot.pack(side="left", padx=(0, 8))
        logo_dot.pack_propagate(False)

        ctk.CTkLabel(brand_row, text="Antigravity",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=t["text_primary"]).pack(side="left")

        self.status_lbl = ctk.CTkLabel(brand_row, text="...",
                                        font=ctk.CTkFont(size=10),
                                        text_color=t["text_muted"])
        self.status_lbl.pack(side="right")

        # Search
        self.search_entry = ctk.CTkEntry(
            self.sidebar_frame,
            placeholder_text="Search conversations...",
            fg_color=t["bg_input"], border_color=t["input_border"], border_width=1,
            corner_radius=6, height=30, text_color=t["text_primary"],
            placeholder_text_color=t["text_muted"], font=ctk.CTkFont(size=12))
        self.search_entry.grid(row=1, column=0, padx=14, pady=(12, 6), sticky="ew")
        self.search_entry.bind("<KeyRelease>", self._on_search_changed)

        # Filter pills
        self._build_filter_pills(t)

        # Conversation list
        self.conv_scroll = ctk.CTkScrollableFrame(
            self.sidebar_frame, fg_color="transparent",
            scrollbar_button_color=t["bg_elevated"],
            scrollbar_button_hover_color=t["accent"], corner_radius=0)
        self.conv_scroll.grid(row=4, column=0, padx=0, pady=(4, 0), sticky="nsew")

        # Sidebar footer
        self._build_sidebar_footer(t)

    def _build_filter_pills(self, t: dict):
        pill_frame = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        pill_frame.grid(row=2, column=0, padx=14, pady=(0, 4), sticky="w")

        self._filter_btns: dict[str, ctk.CTkButton] = {}
        for label in ("All", "Live API", "On Disk"):
            btn = ctk.CTkButton(
                pill_frame, text=label, width=0, height=24, corner_radius=5,
                font=ctk.CTkFont(size=11), fg_color="transparent",
                hover_color=t["bg_row_hover"], text_color=t["text_muted"],
                command=lambda l=label: self._on_filter_changed(l))
            btn.pack(side="left", padx=(0, 2))
            self._filter_btns[label] = btn

        tk.Frame(self.sidebar_frame, height=1, bg=t["border_sidebar"]).grid(
            row=3, column=0, sticky="ew", padx=0, pady=(4, 0))
        self._set_active_filter("All")

    def _set_active_filter(self, label: str):
        t = self.theme
        for lbl, btn in self._filter_btns.items():
            if lbl == label:
                btn.configure(fg_color=t["seg_active_bg"], text_color=t["text_primary"])
            else:
                btn.configure(fg_color="transparent", text_color=t["text_muted"])

    def _build_sidebar_footer(self, t: dict):
        footer = ctk.CTkFrame(self.sidebar_frame, fg_color=t["bg_sidebar"], corner_radius=0)
        footer.grid(row=5, column=0, sticky="ew", padx=0)
        tk.Frame(footer, height=1, bg=t["border_sidebar"]).pack(fill="x")

        btn_row = ctk.CTkFrame(footer, fg_color="transparent")
        btn_row.pack(fill="x", padx=10, pady=8)

        self.recover_btn = ctk.CTkButton(
            btn_row, text="Recover", fg_color=t["accent"], hover_color=t["accent_hover"],
            text_color="#ffffff", font=ctk.CTkFont(size=11, weight="bold"),
            command=self._open_recovery_dialog, height=26, corner_radius=5, width=0)
        self.recover_btn.pack(side="left", padx=(0, 6))

        self.import_btn = ctk.CTkButton(
            btn_row, text="Import", fg_color=t["btn_secondary"],
            hover_color=t["btn_secondary_hover"], text_color=t["btn_secondary_text"],
            border_color=t["btn_secondary_border"], border_width=1,
            font=ctk.CTkFont(size=11), command=self._open_import_dialog,
            height=26, corner_radius=5, width=0)
        self.import_btn.pack(side="left", padx=(0, 4))

        self.refresh_btn = ctk.CTkButton(
            btn_row, text="Refresh", fg_color=t["btn_secondary"],
            hover_color=t["btn_secondary_hover"], text_color=t["btn_secondary_text"],
            border_color=t["btn_secondary_border"], border_width=1,
            font=ctk.CTkFont(size=11), command=self._refresh_all,
            height=26, corner_radius=5, width=0)
        self.refresh_btn.pack(side="left")

    # ── Main panel ────────────────────────────────────────────────────────

    def _build_main_panel(self, t: dict):
        self.main_frame = ctk.CTkFrame(self, corner_radius=0,
                                        fg_color=t["bg_window"], border_width=0)
        self.main_frame.grid(row=0, column=1, sticky="nsew")
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(2, weight=1)

        self._build_header(t)
        self._build_tabs(t)

        self.content_scroll = ctk.CTkScrollableFrame(
            self.main_frame, fg_color="transparent",
            scrollbar_button_color=t["border_subtle"],
            scrollbar_button_hover_color=t["accent"], corner_radius=0)
        self.content_scroll.grid(row=2, column=0, padx=0, pady=0, sticky="nsew")

    def _build_header(self, t: dict):
        self.viewer_header = ctk.CTkFrame(self.main_frame, fg_color=t["bg_sidebar"],
                                           corner_radius=0, border_width=0)
        self.viewer_header.grid(row=0, column=0, sticky="ew")
        self.viewer_header.grid_columnconfigure(0, weight=1)

        tk.Frame(self.viewer_header, height=1, bg=t["border_sidebar"]).pack(
            side="bottom", fill="x")

        top_row = ctk.CTkFrame(self.viewer_header, fg_color="transparent")
        top_row.pack(fill="x", padx=20, pady=(12, 6))

        title_group = ctk.CTkFrame(top_row, fg_color="transparent")
        title_group.pack(side="left", fill="x", expand=True)

        self.title_label = ctk.CTkLabel(
            title_group, text="Select a conversation",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=t["text_primary"], anchor="w")
        self.title_label.pack(side="left")

        self.steps_badge = ctk.CTkLabel(
            title_group, text="",
            font=ctk.CTkFont(family="Consolas", size=11),
            text_color=t["text_muted"], fg_color=t["bg_elevated"],
            corner_radius=4, padx=7, pady=1)
        self.steps_badge.pack(side="left", padx=10)

        self.export_group = ctk.CTkFrame(top_row, fg_color="transparent")
        self.export_group.pack(side="right")

        def _ghost(parent, text, cmd, accent=False):
            return ctk.CTkButton(
                parent, text=text, width=0, height=24, corner_radius=5,
                fg_color=t["accent"] if accent else "transparent",
                hover_color=t["accent_hover"] if accent else t["btn_ghost_hover"],
                text_color="#ffffff" if accent else t["btn_ghost_text"],
                font=ctk.CTkFont(size=11), command=cmd)

        self.md_toggle_btn = _ghost(self.export_group, "MD: ON", self._toggle_md_view, accent=True)
        self.md_toggle_btn.pack(side="left", padx=(0, 4))
        _ghost(self.export_group, "Copy .md", self._copy_as_markdown).pack(side="left", padx=2)
        _ghost(self.export_group, ".json", lambda: self._export_active("json")).pack(side="left", padx=2)
        _ghost(self.export_group, ".html", lambda: self._export_active("html")).pack(side="left", padx=2)
        self.export_db_btn = _ghost(self.export_group, ".db", lambda: self._export_active("db"))
        self.export_db_btn.pack(side="left", padx=2)
        self.export_pb_btn = _ghost(self.export_group, ".pb", lambda: self._export_active("pb"))
        self.export_pb_btn.pack(side="left", padx=(2, 0))

        meta_row = ctk.CTkFrame(self.viewer_header, fg_color="transparent")
        meta_row.pack(fill="x", padx=20, pady=(0, 10))

        self.id_lbl = ctk.CTkLabel(meta_row, text="",
                                    font=ctk.CTkFont(family="Consolas", size=10),
                                    text_color=t["text_faint"])
        self.id_lbl.pack(side="left", padx=(0, 16))

        self.source_lbl = ctk.CTkLabel(meta_row, text="",
                                        font=ctk.CTkFont(size=10),
                                        text_color=t["text_muted"])
        self.source_lbl.pack(side="left", padx=(0, 16))

        self.ws_lbl = ctk.CTkLabel(meta_row, text="",
                                    font=ctk.CTkFont(size=10),
                                    text_color=t["text_muted"])
        self.ws_lbl.pack(side="left")

    def _build_tabs(self, t: dict):
        tabs_bar = ctk.CTkFrame(self.main_frame, fg_color=t["bg_sidebar"], corner_radius=0)
        tabs_bar.grid(row=1, column=0, sticky="ew")
        tk.Frame(tabs_bar, height=1, bg=t["border_sidebar"]).pack(side="bottom", fill="x")

        inner = ctk.CTkFrame(tabs_bar, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=5)

        self._tab_btns: dict[str, ctk.CTkButton] = {}
        for label in ("Chat View", "AI Reasoning", "Tool Logs", "Raw JSON"):
            btn = ctk.CTkButton(
                inner, text=label, width=0, height=26, corner_radius=5,
                fg_color="transparent", hover_color=t["bg_row_hover"],
                text_color=t["text_muted"], font=ctk.CTkFont(size=12),
                command=lambda l=label: self._on_tab_changed(l))
            btn.pack(side="left", padx=(0, 2))
            self._tab_btns[label] = btn
        self._set_active_tab("Chat View")

    def _set_active_tab(self, label: str):
        t = self.theme
        for lbl, btn in self._tab_btns.items():
            if lbl == label:
                btn.configure(fg_color=t["seg_active_bg"], text_color=t["text_primary"])
            else:
                btn.configure(fg_color="transparent", text_color=t["text_muted"])

    # ── Smooth scrolling ──────────────────────────────────────────────────

    def _bind_smooth_scrolling(self):
        def is_inside(child, parent):
            curr = child
            while curr is not None:
                if (curr == parent
                        or curr == getattr(parent, "_parent_canvas", None)
                        or curr == getattr(parent, "_parent_frame", None)):
                    return True
                curr = getattr(curr, "master", None)
            return False

        def on_global_mousewheel(event):
            try:
                w = self.winfo_containing(event.x_root, event.y_root)
            except Exception:
                w = None
            if not w:
                return "break"
            delta = int(-1 * (event.delta / 120))
            if delta == 0:
                delta = -1 if event.delta > 0 else 1

            if is_inside(w, self.sidebar_frame) or is_inside(w, self.conv_scroll):
                canvas = getattr(self.conv_scroll, "_parent_canvas", None)
                if canvas and canvas.winfo_exists():
                    canvas.yview_scroll(delta, "units")
                return "break"

            if is_inside(w, self.main_frame) or is_inside(w, self.content_scroll):
                canvas = getattr(self.content_scroll, "_parent_canvas", None)
                if canvas and canvas.winfo_exists():
                    canvas.yview_scroll(delta, "units")
                    self._schedule_scroll_check()
                return "break"
            return "break"

        self._content_wheel_fn = on_global_mousewheel
        self.bind_all("<MouseWheel>", on_global_mousewheel, add="+")
        self.bind_class("Text", "<MouseWheel>", on_global_mousewheel)

        def on_content_canvas_scrolled(first, last):
            sb = getattr(self.content_scroll, "_scrollbar", None)
            if sb and sb.winfo_exists():
                sb.set(float(first), float(last))
            if float(last) > 0.80:
                self._schedule_scroll_check()

        canvas = getattr(self.content_scroll, "_parent_canvas", None)
        if canvas:
            canvas.configure(yscrollcommand=on_content_canvas_scrolled)

    def _schedule_scroll_check(self):
        if self._scroll_timer:
            self.after_cancel(self._scroll_timer)
        self._scroll_timer = self.after(50, self._check_auto_load_more)

    def _check_auto_load_more(self):
        if self._is_loading_chunk:
            return
        if self.rendered_count >= len(self.active_messages):
            return
        if self.current_tab != "Chat View":
            return
        canvas = getattr(self.content_scroll, "_parent_canvas", None)
        if not canvas or not canvas.winfo_exists():
            return
        try:
            _, y2 = canvas.yview()
            if y2 > 0.78:
                self._render_next_chat_chunk()
        except Exception:
            pass

    # ── Data loading ──────────────────────────────────────────────────────

    def _refresh_all(self):
        self.status_lbl.configure(text="syncing...", text_color=self.theme["text_muted"])
        threading.Thread(target=self._async_load_data, daemon=True).start()

    def _async_load_data(self):
        connected = self.client.refresh_connection()
        ep = self.client.endpoint
        disk_map = scan_disk_conversations()
        api_items = self.client.get_all_trajectories() if connected else {}

        merged = dict(disk_map)
        for cid, api_info in api_items.items():
            if cid in merged:
                merged[cid].source = "api"
                if api_info.get("summary"):
                    merged[cid].title = api_info["summary"]
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
        items.sort(key=lambda x: x.last_modified_time or "", reverse=True)
        self.after(0, lambda: self._on_data_loaded(items, connected, ep))

    def _on_data_loaded(self, items: list[ConversationSummary], connected: bool, ep: Any):
        self.conversations = items
        self._restore_status_label()
        self._render_conversation_list()
        if self.conversations:
            target = next((c for c in self.conversations if c.id == self.active_id),
                          self.conversations[0])
            if target.id != self.active_id:
                self._select_conversation(target)

    # ── Sidebar list ──────────────────────────────────────────────────────

    def _on_search_changed(self, event=None):
        self.search_query = self.search_entry.get().strip().lower()
        self._render_conversation_list()

    def _on_filter_changed(self, choice: str):
        self.current_filter = choice
        self._set_active_filter(choice)
        self._render_conversation_list()

    def _render_conversation_list(self):
        t = self.theme
        for widget in self.conv_scroll.winfo_children():
            widget.destroy()

        filtered = []
        for c in self.conversations:
            if self.current_filter == "Live API" and c.source != "api":
                continue
            if self.current_filter == "On Disk" and c.source != "disk":
                continue
            if self.search_query:
                in_title = self.search_query in c.title.lower()
                in_ws = c.workspace and self.search_query in c.workspace.lower()
                in_preview = c.preview and self.search_query in c.preview.lower()
                if not (in_title or in_ws or in_preview):
                    continue
            filtered.append(c)

        if not filtered:
            ctk.CTkLabel(self.conv_scroll, text="No conversations found.",
                         font=ctk.CTkFont(size=12), text_color=t["text_muted"]).pack(pady=24)
            return

        from collections import defaultdict
        from datetime import date, datetime
        groups: dict[str, list] = defaultdict(list)
        for c in filtered:
            day = c.last_modified_time[:10] if c.last_modified_time else "Unknown"
            groups[day].append(c)

        for day in sorted(groups.keys(), reverse=True):
            # Day label
            try:
                d = datetime.strptime(day, "%Y-%m-%d").date()
                today = date.today()
                delta = (today - d).days
                if delta == 0:
                    day_lbl = "TODAY"
                elif delta == 1:
                    day_lbl = "YESTERDAY"
                elif delta < 7:
                    day_lbl = d.strftime("%A").upper()
                else:
                    day_lbl = d.strftime("%b %d").upper()
            except Exception:
                day_lbl = "EARLIER"

            ctk.CTkLabel(self.conv_scroll, text=day_lbl,
                         font=ctk.CTkFont(size=9, weight="bold"),
                         text_color=t["text_faint"], anchor="w").pack(
                             fill="x", padx=14, pady=(10, 2))

            for c in groups[day]:
                self._render_conv_row(c, t)

    def _render_conv_row(self, c: ConversationSummary, t: dict):
        is_active = (c.id == self.active_id)
        row_bg = t["bg_row_active"] if is_active else t["bg_sidebar"]

        outer = tk.Frame(self.conv_scroll, bg=row_bg, cursor="hand2")
        outer.pack(fill="x")

        accent_bar = tk.Frame(outer, width=2,
                               bg=t["accent"] if is_active else row_bg)
        accent_bar.pack(side="left", fill="y")

        content = ctk.CTkFrame(outer,
                                fg_color=t["bg_row_active"] if is_active else "transparent",
                                corner_radius=0, cursor="hand2")
        content.pack(side="left", fill="x", expand=True)

        title_row = ctk.CTkFrame(content, fg_color="transparent")
        title_row.pack(fill="x", padx=(10, 12), pady=(8, 1))

        clean_title = fix_arabic(c.title[:52])
        t_lbl = ctk.CTkLabel(
            title_row, text=clean_title,
            font=ctk.CTkFont(size=12, weight="bold" if is_active else "normal"),
            text_color=t["text_primary"] if is_active else t["text_secondary"],
            anchor="w")
        t_lbl.pack(side="left", fill="x", expand=True)

        if c.last_modified_time:
            ctk.CTkLabel(title_row, text=c.last_modified_time[5:10],
                         font=ctk.CTkFont(size=10),
                         text_color=t["text_faint"]).pack(side="right")

        sub_row = ctk.CTkFrame(content, fg_color="transparent")
        sub_row.pack(fill="x", padx=(10, 12), pady=(0, 7))

        if c.workspace:
            sub_text = c.workspace.replace("\\", "/").split("/")[-1]
        elif c.preview and not c.preview.startswith("file:"):
            sub_text = c.preview[:50]
        else:
            sub_text = c.id[:14]

        p_lbl = ctk.CTkLabel(sub_row, text=fix_arabic(sub_text),
                              font=ctk.CTkFont(size=10),
                              text_color=t["text_muted"], anchor="w")
        p_lbl.pack(side="left")

        if c.step_count:
            ctk.CTkLabel(sub_row, text=f"{c.step_count}s",
                         font=ctk.CTkFont(size=9),
                         text_color=t["text_faint"]).pack(side="right", padx=(0, 4))

        src_color = t["status_green"] if c.source == "api" else t["text_faint"]
        ctk.CTkLabel(sub_row, text=c.source.upper(),
                     font=ctk.CTkFont(size=9),
                     text_color=src_color).pack(side="right")

        # Bottom separator
        tk.Frame(outer, height=1, bg=t["border_sidebar"]).pack(fill="x", side="bottom")

        # Click bindings
        for w in [outer, accent_bar, content, title_row, t_lbl, sub_row, p_lbl]:
            w.bind("<Button-1>", lambda e, item=c: self._select_conversation(item))

        # Hover (inactive only)
        if not is_active:
            def on_enter(e, o=outer, ct=content):
                o.configure(bg=t["bg_row_hover"])
                ct.configure(fg_color=t["bg_row_hover"])
            def on_leave(e, o=outer, ct=content):
                o.configure(bg=t["bg_sidebar"])
                ct.configure(fg_color="transparent")
            for w in [outer, accent_bar, content, title_row, t_lbl, sub_row, p_lbl]:
                w.bind("<Enter>", on_enter)
                w.bind("<Leave>", on_leave)

    # ── Conversation selection ────────────────────────────────────────────

    def _select_conversation(self, c: ConversationSummary):
        if c.id == self.active_id:
            return
        self.active_id = c.id
        self.active_summary = c
        self.active_messages = []
        self.rendered_count = 0
        self._is_loading_chunk = False
        self.load_more_frame = None
        self._render_conversation_list()
        self._update_header(c)
        self._switch_tab(self.current_tab)

    def _update_header(self, c: ConversationSummary):
        t = self.theme
        self.title_label.configure(text=fix_arabic(c.title[:70]))
        self.steps_badge.configure(text=f"{c.step_count} steps" if c.step_count else "")
        self.id_lbl.configure(text=c.id[:12])
        self.source_lbl.configure(
            text=c.source,
            text_color=t["status_green"] if c.source == "api" else t["text_muted"])
        ws_name = c.workspace.replace("\\", "/").split("/")[-1] if c.workspace else ""
        self.ws_lbl.configure(text=ws_name)

    def _clear_content(self):
        for w in self.content_scroll.winfo_children():
            w.destroy()

    def _on_tab_changed(self, tab: str):
        self.current_tab = tab
        self._set_active_tab(tab)
        self._switch_tab(tab)

    def _switch_tab(self, tab: str):
        self._clear_content()
        self.rendered_count = 0
        self._is_loading_chunk = False
        self.load_more_frame = None
        if not self.active_summary:
            self._show_empty_state()
            return
        if tab == "Chat View":
            self._load_and_render_chat()
        elif tab == "AI Reasoning":
            self._load_messages_then(self._render_reasoning_view)
        elif tab == "Tool Logs":
            self._load_messages_then(self._render_tools_view)
        elif tab == "Raw JSON":
            self._load_messages_then(self._render_raw_view)

    def _show_empty_state(self):
        t = self.theme
        ctk.CTkLabel(self.content_scroll,
                     text="Select a conversation from the sidebar",
                     font=ctk.CTkFont(size=13),
                     text_color=t["text_muted"]).pack(pady=60)

    def _load_and_render_chat(self):
        def _load():
            msgs = self._fetch_messages(self.active_summary)
            self.active_messages = msgs
            self.after(0, self._render_next_chat_chunk)
        threading.Thread(target=_load, daemon=True).start()

    def _load_messages_then(self, callback):
        def _load():
            if not self.active_messages:
                self.active_messages = self._fetch_messages(self.active_summary)
            self.after(0, callback)
        threading.Thread(target=_load, daemon=True).start()

    def _fetch_messages(self, summary: ConversationSummary) -> list[ConversationMessage]:
        try:
            if summary.source == "api":
                raw = self.client.get_trajectory(summary.id)
                if raw:
                    return parse_api_trajectory(raw)
            lines = read_transcript_lines(summary.id)
            if lines:
                return parse_transcript_records(lines)
        except Exception:
            pass
        return []

    # ── Progressive chat rendering ────────────────────────────────────────

    def _render_next_chat_chunk(self):
        if self._is_loading_chunk:
            return
        self._is_loading_chunk = True
        t = self.theme

        if self.load_more_frame and self.load_more_frame.winfo_exists():
            self.load_more_frame.destroy()
            self.load_more_frame = None

        total = len(self.active_messages)
        start = self.rendered_count
        end = min(start + self.CHUNK_SIZE, total)

        if start == 0 and total == 0:
            ctk.CTkLabel(self.content_scroll, text="No messages in this conversation.",
                         font=ctk.CTkFont(size=12),
                         text_color=t["text_muted"]).pack(pady=30)
            self._is_loading_chunk = False
            return

        for i in range(start, end):
            self._render_single_message(self.active_messages[i])

        self.rendered_count = end
        remaining = total - end

        if remaining > 0:
            btn_frame = ctk.CTkFrame(self.content_scroll, fg_color="transparent")
            btn_frame.pack(fill="x", padx=24, pady=12)
            self.load_more_frame = btn_frame

            ctk.CTkButton(
                btn_frame,
                text=f"Load {min(self.CHUNK_SIZE, remaining)} more  ({remaining} remaining)",
                fg_color=t["bg_card"], hover_color=t["bg_card_hover"],
                text_color=t["text_muted"], border_color=t["border_subtle"],
                border_width=1, font=ctk.CTkFont(size=11), height=28,
                corner_radius=6, command=self._render_next_chat_chunk).pack(side="left", padx=4)

            ctk.CTkButton(
                btn_frame, text=f"Load all ({remaining})",
                fg_color=t["accent"], hover_color=t["accent_hover"],
                text_color="#ffffff", font=ctk.CTkFont(size=11, weight="bold"),
                height=28, corner_radius=6,
                command=self._load_all_remaining_messages).pack(side="left", padx=4)
        else:
            end_frame = ctk.CTkFrame(self.content_scroll, fg_color="transparent")
            end_frame.pack(fill="x", padx=24, pady=16)
            self.load_more_frame = end_frame
            ctk.CTkLabel(end_frame, text=f"— all {total} messages loaded —",
                         font=ctk.CTkFont(size=10),
                         text_color=t["text_faint"]).pack(anchor="center")

        self._is_loading_chunk = False

    def _load_all_remaining_messages(self):
        if self.rendered_count < len(self.active_messages):
            self._render_next_chat_chunk()
            if self.rendered_count < len(self.active_messages):
                self.after(20, self._load_all_remaining_messages)

    # ── Message rendering ─────────────────────────────────────────────────

    def _render_single_message(self, msg: ConversationMessage):
        t = self.theme
        wrapper = ctk.CTkFrame(self.content_scroll, fg_color="transparent")
        wrapper.pack(fill="x", padx=20, pady=(0, 2))
        if msg.role == "user":
            self._render_user_message(wrapper, msg, t)
        else:
            self._render_assistant_message(wrapper, msg, t)

    def _render_user_message(self, parent, msg: ConversationMessage, t: dict):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x")
        # Spacer pushes bubble right
        ctk.CTkFrame(row, fg_color="transparent").pack(side="left", fill="x", expand=True)

        bubble = ctk.CTkFrame(row, fg_color=t["user_bubble"], corner_radius=10,
                               border_color=t["user_bubble_border"], border_width=1)
        bubble.pack(side="right", padx=(60, 0))

        hdr = ctk.CTkFrame(bubble, fg_color="transparent")
        hdr.pack(fill="x", padx=10, pady=(7, 2))

        ctk.CTkLabel(hdr, text="You", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color="#60a5fa").pack(side="left")

        ctk.CTkButton(hdr, text="Copy", width=0, height=18, corner_radius=4,
                      fg_color="transparent", hover_color=t["btn_ghost_hover"],
                      text_color=t["text_faint"], font=ctk.CTkFont(size=9),
                      command=lambda c=msg.content: self._copy_single_message(c)
                      ).pack(side="right", padx=(0, 4))

        if msg.timestamp:
            ctk.CTkLabel(hdr, text=msg.timestamp[11:16],
                         font=ctk.CTkFont(size=9),
                         text_color=t["text_faint"]).pack(side="right", padx=(0, 6))

        if msg.content:
            if self.md_view_enabled:
                md = MarkdownViewer(bubble, scroll_callback=self._content_wheel_fn,
                                    is_dark=True, bg=t["user_bubble"])
                md.pack(fill="x", padx=6, pady=(2, 6))
                md.set_markdown(msg.content)
            else:
                clean = fix_arabic(msg.content)
                tb = ctk.CTkTextbox(bubble, fg_color="transparent",
                                    text_color=t["text_primary"],
                                    font=ctk.CTkFont(size=12), wrap="word",
                                    height=max(40, min(280, len(clean.splitlines()) * 19)))
                tb.pack(fill="x", padx=10, pady=(0, 8))
                tb.insert("1.0", clean)
                tb.configure(state="disabled")

    def _render_assistant_message(self, parent, msg: ConversationMessage, t: dict):
        hdr = ctk.CTkFrame(parent, fg_color="transparent")
        hdr.pack(fill="x", pady=(8, 0))

        ctk.CTkLabel(hdr, text="Assistant", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=t["text_secondary"]).pack(side="left")

        if msg.model:
            ctk.CTkLabel(hdr, text=f" {msg.model}",
                         font=ctk.CTkFont(family="Consolas", size=9),
                         text_color=t["text_faint"], fg_color=t["bg_elevated"],
                         corner_radius=3, padx=5, pady=1).pack(side="left", padx=4)

        if msg.timestamp:
            ctk.CTkLabel(hdr, text=msg.timestamp[11:16],
                         font=ctk.CTkFont(size=9),
                         text_color=t["text_faint"]).pack(side="left", padx=6)

        ctk.CTkButton(hdr, text="Copy", width=0, height=18, corner_radius=4,
                      fg_color="transparent", hover_color=t["btn_ghost_hover"],
                      text_color=t["text_faint"], font=ctk.CTkFont(size=9),
                      command=lambda c=msg.content: self._copy_single_message(c)
                      ).pack(side="right")

        if msg.thinking:
            self._render_thinking_block(parent, msg, t)

        if msg.content:
            if self.md_view_enabled:
                md = MarkdownViewer(parent, scroll_callback=self._content_wheel_fn,
                                    is_dark=True, bg=t["bg_window"])
                md.pack(fill="x", pady=(4, 2))
                md.set_markdown(msg.content)
            else:
                clean = fix_arabic(msg.content)
                tb = ctk.CTkTextbox(parent, fg_color="transparent",
                                    text_color=t["text_primary"],
                                    font=ctk.CTkFont(size=12), wrap="word",
                                    height=max(40, min(320, len(clean.splitlines()) * 19)))
                tb.pack(fill="x", pady=(4, 2))
                tb.insert("1.0", clean)
                tb.configure(state="disabled")

        if msg.tools:
            self._render_tool_chips(parent, msg, t)

        tk.Frame(parent, height=1, bg=t["border_sidebar"]).pack(fill="x", pady=(8, 0))

    def _render_thinking_block(self, parent, msg: ConversationMessage, t: dict):
        dur = f" · {msg.thinking_duration}" if msg.thinking_duration else ""
        container = ctk.CTkFrame(parent, fg_color=t["thinking_bg"],
                                  border_color=t["thinking_border"],
                                  border_width=1, corner_radius=6)
        container.pack(fill="x", pady=(4, 4))

        is_expanded = [False]
        toggle_btn = ctk.CTkButton(
            container, text=f"▶  Reasoning process{dur}   (click to expand)",
            font=ctk.CTkFont(size=10), text_color=t["text_muted"],
            fg_color="transparent", hover_color=t["bg_card_hover"],
            anchor="w", height=26, corner_radius=4)
        toggle_btn.pack(fill="x", padx=6, pady=2)

        t_box = ctk.CTkTextbox(container, fg_color=t["bg_elevated"],
                                text_color=t["text_secondary"],
                                font=ctk.CTkFont(family="Consolas", size=10),
                                height=110, corner_radius=4)
        t_box.insert("1.0", fix_arabic(msg.thinking))
        t_box.configure(state="disabled")

        def toggle(btn=toggle_btn, box=t_box, state=is_expanded, d=dur):
            if state[0]:
                box.pack_forget()
                btn.configure(text=f"▶  Reasoning process{d}   (click to expand)")
                state[0] = False
            else:
                box.pack(fill="x", padx=8, pady=(0, 8))
                btn.configure(text=f"▼  Reasoning process{d}   (click to collapse)")
                state[0] = True
        toggle_btn.configure(command=toggle)

    def _render_tool_chips(self, parent, msg: ConversationMessage, t: dict):
        chips = ctk.CTkFrame(parent, fg_color=t["tool_bg"],
                              border_color=t["tool_border"],
                              border_width=1, corner_radius=6)
        chips.pack(fill="x", pady=(2, 4))
        for tool_item in msg.tools:
            if tool_item.name == "run_command":
                cmd = tool_item.input_data.get("command", "")
                ctk.CTkLabel(chips, text=f"$  {cmd}",
                             font=ctk.CTkFont(family="Consolas", size=10),
                             text_color=t["status_amber"], anchor="w").pack(
                                 fill="x", padx=10, pady=2)
            elif tool_item.diff:
                ctk.CTkLabel(chips, text=f"Edit: {tool_item.input_data.get('file', '')}",
                             font=ctk.CTkFont(family="Consolas", size=10),
                             text_color=t["status_green"], anchor="w").pack(
                                 fill="x", padx=10, pady=2)
            elif tool_item.summary:
                ctk.CTkLabel(chips, text=f"{tool_item.name}: {tool_item.summary}",
                             font=ctk.CTkFont(size=10),
                             text_color=t["text_muted"], anchor="w").pack(
                                 fill="x", padx=10, pady=2)

    # ── Tab views ─────────────────────────────────────────────────────────

    def _render_reasoning_view(self):
        t = self.theme
        thinkings = [m for m in self.active_messages if m.thinking]
        if not thinkings:
            ctk.CTkLabel(self.content_scroll,
                         text="No reasoning steps recorded in this session.",
                         font=ctk.CTkFont(size=12),
                         text_color=t["text_muted"]).pack(pady=30)
            return
        for i, m in enumerate(thinkings):
            card = ctk.CTkFrame(self.content_scroll, fg_color=t["bg_card"],
                                border_color=t["border_card"], border_width=1, corner_radius=8)
            card.pack(fill="x", padx=20, pady=6)
            ctk.CTkLabel(card, text=f"Step #{i+1}  ·  {m.thinking_duration or 'instant'}",
                         font=ctk.CTkFont(size=11, weight="bold"),
                         text_color=t["text_secondary"], anchor="w").pack(
                             fill="x", padx=12, pady=(10, 4))
            box = ctk.CTkTextbox(card, fg_color=t["thinking_bg"],
                                  text_color=t["text_primary"],
                                  font=ctk.CTkFont(family="Consolas", size=10),
                                  height=160, corner_radius=6)
            box.pack(fill="x", padx=12, pady=(0, 12))
            box.insert("1.0", fix_arabic(m.thinking))
            box.configure(state="disabled")

    def _render_tools_view(self):
        t = self.theme
        all_tools = []
        for m in self.active_messages:
            all_tools.extend(m.tools)
        if not all_tools:
            ctk.CTkLabel(self.content_scroll,
                         text="No commands or code edits in this session.",
                         font=ctk.CTkFont(size=12),
                         text_color=t["text_muted"]).pack(pady=30)
            return
        for tool_item in all_tools:
            card = ctk.CTkFrame(self.content_scroll, fg_color=t["bg_card"],
                                border_color=t["border_card"], border_width=1, corner_radius=8)
            card.pack(fill="x", padx=20, pady=5)
            title_txt = tool_item.name
            if tool_item.action_type == "command":
                title_txt = f"Terminal  (exit: {tool_item.exit_code if tool_item.exit_code is not None else 0})"
            elif tool_item.diff:
                title_txt = f"Edit: {tool_item.input_data.get('file', '')}"
            ctk.CTkLabel(card, text=title_txt,
                         font=ctk.CTkFont(size=11, weight="bold"),
                         text_color=t["status_amber"] if "Terminal" in title_txt else t["status_green"],
                         anchor="w").pack(fill="x", padx=12, pady=(8, 2))
            body = tool_item.diff or tool_item.output_data or json.dumps(tool_item.input_data, indent=2)
            box = ctk.CTkTextbox(card, fg_color=t["tool_bg"],
                                  text_color=t["text_primary"],
                                  font=ctk.CTkFont(family="Consolas", size=10),
                                  height=120, corner_radius=6)
            box.pack(fill="x", padx=12, pady=(0, 10))
            box.insert("1.0", body)
            box.configure(state="disabled")

    def _render_raw_view(self):
        if not self.active_summary:
            return
        t = self.theme
        raw = export_json(self.active_summary, self.active_messages)
        box = ctk.CTkTextbox(self.content_scroll, fg_color=t["bg_card"],
                              text_color=t["accent"],
                              font=ctk.CTkFont(family="Consolas", size=11),
                              height=600, corner_radius=8,
                              border_color=t["border_card"], border_width=1)
        box.pack(fill="both", expand=True, padx=20, pady=12)
        box.insert("1.0", raw)
        box.configure(state="disabled")

    # ── Actions ───────────────────────────────────────────────────────────

    def _toggle_md_view(self):
        self.md_view_enabled = not self.md_view_enabled
        t = self.theme
        if self.md_view_enabled:
            self.md_toggle_btn.configure(text="MD: ON", fg_color=t["accent"],
                                          hover_color=t["accent_hover"], text_color="#ffffff")
        else:
            self.md_toggle_btn.configure(text="MD: OFF", fg_color="transparent",
                                          hover_color=t["btn_ghost_hover"],
                                          text_color=t["btn_ghost_text"])
        if self.active_summary and self.current_tab == "Chat View":
            self._clear_content()
            self.rendered_count = 0
            self._render_next_chat_chunk()

    def _copy_single_message(self, text: str):
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status_lbl.configure(text="copied!", text_color=self.theme["status_green"])
        self.after(2000, self._restore_status_label)

    def _restore_status_label(self):
        connected = self.client.is_connected()
        ep = self.client.endpoint
        if connected and ep:
            self.status_lbl.configure(
                text=f"live · {ep.port}", text_color=self.theme["status_green"])
        else:
            self.status_lbl.configure(
                text="offline", text_color=self.theme["status_amber"])

    def _copy_as_markdown(self):
        if not self.active_summary:
            return
        md = export_markdown(self.active_summary, self.active_messages)
        self.clipboard_clear()
        self.clipboard_append(md)
        messagebox.showinfo("Copied", "Conversation copied to clipboard as Markdown.")

    def _export_active(self, fmt: str):
        if not self.active_summary:
            messagebox.showwarning("Warning", "Please select a conversation first.")
            return
        clean_title = "".join(
            c for c in self.active_summary.title if c.isalnum() or c in (" ", "-", "_"))[:30].strip()
        default_name = f"{clean_title}_{self.active_summary.id[:8]}.{fmt}"
        file_types = {
            "md":   [("Markdown File", "*.md")],
            "json": [("JSON File", "*.json")],
            "html": [("HTML Document", "*.html")],
            "db":   [("SQLite Database", "*.db")],
            "pb":   [("Protobuf File", "*.pb")],
        }
        save_path = filedialog.asksaveasfilename(
            defaultextension=f".{fmt}",
            filetypes=file_types.get(fmt, [("All Files", "*.*")]),
            initialfile=default_name, title=f"Export as {fmt.upper()}")
        if not save_path:
            return
        try:
            if fmt in ("db", "pb"):
                res = export_database_file(self.active_summary, Path(save_path), fmt=fmt)
                if res.get("success"):
                    messagebox.showinfo("Exported", f"Saved:\n{save_path}")
                else:
                    messagebox.showerror("Export Failed", res.get("error", "Failed."))
                return
            if fmt == "json":
                content = export_json(self.active_summary, self.active_messages)
            elif fmt == "html":
                content = export_html(self.active_summary, self.active_messages)
            else:
                content = export_markdown(self.active_summary, self.active_messages)
            Path(save_path).write_text(content, encoding="utf-8")
            messagebox.showinfo("Exported", f"Saved:\n{save_path}")
        except Exception as e:
            messagebox.showerror("Export Failed", str(e))

    def _open_recovery_dialog(self):
        RecoveryDialog(self)

    def _open_import_dialog(self):
        file_path = filedialog.askopenfilename(
            title="Import Conversation",
            filetypes=[
                ("Supported Formats (*.db, *.pb, *.json)", "*.db;*.pb;*.json"),
                ("SQLite Databases (*.db)", "*.db"),
                ("JSON Exports (*.json)", "*.json"),
                ("All Files", "*.*"),
            ])
        if not file_path:
            return
        p = Path(file_path)
        ext = p.suffix.lower()
        if ext in (".db", ".pb"):
            res = import_database_file(p, self.client)
        elif ext == ".json":
            res = import_json_export(p)
        else:
            messagebox.showerror("Error", f"Unsupported file type: {ext}")
            return
        if res.get("success"):
            messagebox.showinfo("Import Success", res.get("message", "Import completed!"))
            self._refresh_all()
        else:
            messagebox.showerror("Import Error", res.get("error", "Failed importing file."))


# ── Recovery Dialog ───────────────────────────────────────────────────────────

class RecoveryDialog(ctk.CTkToplevel):
    def __init__(self, master: AntigravityGUI):
        super().__init__(master)
        self.master_app = master
        t = master.theme

        self.title("Recover Unindexed Conversations")
        self.geometry("560x440")
        self.minsize(480, 360)
        self.configure(fg_color=t["bg_window"])
        self.transient(master)
        self.grab_set()

        self._build_ui()
        threading.Thread(target=self._scan, daemon=True).start()

    def _build_ui(self):
        t = self.master_app.theme
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        hdr = ctk.CTkFrame(self, fg_color=t["bg_sidebar"], corner_radius=0)
        hdr.grid(row=0, column=0, sticky="ew")
        tk.Frame(hdr, height=1, bg=t["border_sidebar"]).pack(side="bottom", fill="x")
        ctk.CTkLabel(hdr, text="Crash Recovery & Session Reactivation",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=t["text_primary"]).pack(padx=16, pady=(12, 2), anchor="w")
        ctk.CTkLabel(hdr,
                     text="Scans disk for orphaned sessions and reloads them into LanguageServer.",
                     font=ctk.CTkFont(size=10),
                     text_color=t["text_muted"]).pack(padx=16, pady=(0, 10), anchor="w")

        stats = ctk.CTkFrame(self, fg_color=t["bg_card"],
                              border_color=t["border_card"], border_width=1, corner_radius=6)
        stats.grid(row=1, column=0, padx=16, pady=10, sticky="ew")
        stats.grid_columnconfigure((0, 1, 2), weight=1)
        self.m_disk = self._metric(stats, 0, "On Disk", "0")
        self.m_api  = self._metric(stats, 1, "In LanguageServer", "0")
        self.m_lost = self._metric(stats, 2, "Unindexed", "0", color=t["status_amber"])

        self.log_box = ctk.CTkTextbox(self, fg_color=t["bg_card"],
                                       text_color=t["text_secondary"],
                                       font=ctk.CTkFont(family="Consolas", size=10),
                                       corner_radius=6, border_color=t["border_card"],
                                       border_width=1)
        self.log_box.grid(row=2, column=0, padx=16, pady=(0, 8), sticky="nsew")

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=3, column=0, padx=16, pady=(0, 14), sticky="ew")

        self.start_btn = ctk.CTkButton(
            footer, text="Reactivate All Sessions",
            fg_color=t["accent"], hover_color=t["accent_hover"],
            text_color="#ffffff", font=ctk.CTkFont(size=12, weight="bold"),
            command=self._start_recovery, height=30, corner_radius=6)
        self.start_btn.pack(side="right")

        ctk.CTkButton(footer, text="Close",
                      fg_color=t["btn_secondary"], hover_color=t["btn_secondary_hover"],
                      text_color=t["btn_secondary_text"],
                      border_color=t["btn_secondary_border"], border_width=1,
                      font=ctk.CTkFont(size=12), command=self.destroy,
                      height=30, corner_radius=6).pack(side="left")

    def _metric(self, parent, col: int, label: str, val: str, color=None):
        t = self.master_app.theme
        color = color or t["text_primary"]
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.grid(row=0, column=col, padx=8, pady=10)
        v = ctk.CTkLabel(f, text=val, font=ctk.CTkFont(size=18, weight="bold"),
                          text_color=color)
        v.pack()
        ctk.CTkLabel(f, text=label, font=ctk.CTkFont(size=10),
                     text_color=t["text_muted"]).pack()
        return v

    def _scan(self):
        engine = self.master_app.recovery_engine
        res = engine.scan_unindexed()
        def _update():
            self.m_disk.configure(text=str(res["total_disk"]))
            self.m_api.configure(text=str(res["total_api"]))
            self.m_lost.configure(text=str(res["unindexed_count"]))
            self.unindexed_ids = res["unindexed_ids"]
            if not res["connected"]:
                self.log_box.insert("end",
                    "Notice: LanguageServer is offline.\nYou can browse and export sessions offline.\n\n")
            else:
                self.log_box.insert("end",
                    f"Discovered {len(self.unindexed_ids)} sessions ready for reactivation.\n\n")
        self.after(0, _update)

    def _start_recovery(self):
        self.start_btn.configure(state="disabled", text="Reactivating...")
        threading.Thread(target=self._run_recovery_async, daemon=True).start()

    def _run_recovery_async(self):
        engine = self.master_app.recovery_engine
        def progress(cid, current, total):
            self.after(0, lambda: self.log_box.insert(
                "end", f"[{current}/{total}] {cid[:8]}...\n"))
            self.after(0, lambda: self.log_box.see("end"))
        res = engine.run_recovery(progress_callback=progress)
        self.after(0, lambda: self._on_done(res))

    def _on_done(self, res: dict):
        self.start_btn.configure(state="normal", text="Reactivation Finished")
        if res.get("success"):
            self.log_box.insert("end",
                f"\nDone — {res.get('activated_count', 0)} sessions reactivated.\n")
            self.master_app._refresh_all()
        else:
            self.log_box.insert("end", f"\nFailed: {res.get('error', 'Error')}\n")
        self.log_box.see("end")


# ─────────────────────────────────────────────────────────────────────────────

def start_gui():
    app = AntigravityGUI()
    app.mainloop()


if __name__ == "__main__":
    start_gui()
