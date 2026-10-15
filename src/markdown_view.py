"""Rich Markdown renderer for CustomTkinter — premium dark palette with Arabic BiDi."""

import re
import tkinter as tk
from typing import Callable, Optional

from src.arabic import fix_arabic

# ── Premium dark palette (mirrors THEMES["dark"] in gui_app.py) ──────────────
_BG_SURFACE       = "#19191F"   # card / assistant bubble bg
_BG_CODE_HDR      = "#111115"
_BG_CODE_BLOCK    = "#0D0D10"
_BG_CODE_FOOTER   = "#111115"
_BG_INLINE_CODE   = "#222228"

_FG_PRIMARY       = "#F5F5F7"
_FG_SECONDARY     = "#A1A1AA"
_FG_MUTED         = "#71717A"
_FG_ACCENT        = "#3B82F6"   # blue accent
_FG_ACCENT2       = "#60A5FA"   # lighter blue for h2
_FG_H3            = "#818CF8"   # indigo for h3
_FG_BOLD          = "#F5F5F7"
_FG_ITALIC        = "#A1A1AA"
_FG_INLINE_CODE   = "#F59E0B"   # amber code token
_FG_CODE_HDR      = "#71717A"
_FG_CODE_BLOCK    = "#D4D4D4"
_FG_BULLET        = "#3B82F6"
_FG_CHECK_DONE    = "#22C55E"
_FG_CHECK_TODO    = "#71717A"
_FG_QUOTE         = "#71717A"
_FG_DIVIDER       = "#303039"


class MarkdownViewer(tk.Text):
    """High-performance Markdown renderer — premium dark design, Arabic BiDi."""

    def __init__(
        self,
        master,
        scroll_callback: Optional[Callable] = None,
        is_dark: bool = True,
        bg: Optional[str] = None,
        **kwargs,
    ):
        self.is_dark = True          # Always dark — single cohesive palette
        self._last_width = 0
        self.scroll_callback = scroll_callback

        resolved_bg = bg if bg else _BG_SURFACE

        super().__init__(
            master,
            bg=resolved_bg,
            fg=_FG_PRIMARY,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            wrap="word",
            font=("Segoe UI", 11),
            padx=14,
            pady=10,
            cursor="arrow",
            selectbackground="#1E3A6E",
            selectforeground=_FG_PRIMARY,
            insertbackground=_FG_PRIMARY,
            **kwargs,
        )

        self._setup_tags()
        self._bind_events()

    def set_theme(self, is_dark: bool, bg_color: str):
        """Kept for API compatibility — always uses dark palette."""
        self.configure(bg=bg_color if bg_color else _BG_SURFACE)
        self._setup_tags()

    def _setup_tags(self):
        # ── Headings ─────────────────────────────────────────────────────────
        self.tag_configure("h1", font=("Segoe UI", 14, "bold"),
                           foreground=_FG_PRIMARY,  spacing1=10, spacing3=5)
        self.tag_configure("h2", font=("Segoe UI", 12, "bold"),
                           foreground=_FG_ACCENT2,  spacing1=8,  spacing3=4)
        self.tag_configure("h3", font=("Segoe UI", 11, "bold"),
                           foreground=_FG_H3,        spacing1=6,  spacing3=3)

        # ── Inline typography ─────────────────────────────────────────────────
        self.tag_configure("bold",        font=("Segoe UI", 11, "bold"),   foreground=_FG_BOLD)
        self.tag_configure("italic",      font=("Segoe UI", 11, "italic"), foreground=_FG_ITALIC)
        self.tag_configure("code_inline", font=("Consolas", 10),
                           background=_BG_INLINE_CODE, foreground=_FG_INLINE_CODE)

        # ── Code blocks ───────────────────────────────────────────────────────
        self.tag_configure(
            "code_header",
            font=("Consolas", 9, "bold"),
            foreground=_FG_CODE_HDR,
            background=_BG_CODE_HDR,
            lmargin1=12, lmargin2=12,
            spacing1=6, spacing3=2,
        )
        self.tag_configure(
            "code_block",
            font=("Consolas", 10),
            background=_BG_CODE_BLOCK,
            foreground=_FG_CODE_BLOCK,
            lmargin1=12, lmargin2=12,
            rmargin=12,
            spacing1=1, spacing3=1,
        )
        self.tag_configure(
            "code_footer",
            font=("Consolas", 8),
            foreground=_FG_DIVIDER,
            background=_BG_CODE_FOOTER,
            lmargin1=12, lmargin2=12,
            spacing1=1, spacing3=8,
        )

        # ── Lists & checkboxes ────────────────────────────────────────────────
        self.tag_configure("bullet_dot",       font=("Segoe UI", 11, "bold"),
                           foreground=_FG_BULLET, lmargin1=14, lmargin2=28)
        self.tag_configure("bullet",           font=("Segoe UI", 11),
                           lmargin1=14, lmargin2=28, spacing1=2, spacing3=2)
        self.tag_configure("checkbox_checked", font=("Segoe UI", 11, "bold"),
                           foreground=_FG_CHECK_DONE)
        self.tag_configure("checkbox_empty",   font=("Segoe UI", 11),
                           foreground=_FG_CHECK_TODO)

        # ── Block-level extras ────────────────────────────────────────────────
        self.tag_configure("quote",   font=("Segoe UI", 10, "italic"),
                           foreground=_FG_QUOTE,
                           lmargin1=16, lmargin2=16, spacing1=3, spacing3=3)
        self.tag_configure("divider", font=("Segoe UI", 8),
                           foreground=_FG_DIVIDER,   spacing1=6, spacing3=6)
        self.tag_configure("muted",   font=("Segoe UI", 10),
                           foreground=_FG_SECONDARY)

    def _bind_events(self):
        def _on_wheel(event):
            if self.scroll_callback:
                self.scroll_callback(event)
            return "break"

        self.bind("<MouseWheel>", _on_wheel)
        self.bind("<Configure>", self._on_configure)

    def _on_configure(self, event):
        if abs(event.width - self._last_width) > 20:
            self._last_width = event.width
            self._recalculate_height()

    def _recalculate_height(self):
        try:
            dlines = self.count("1.0", "end", "displaylines")
            if dlines and dlines[0] > 0:
                self.configure(height=dlines[0])
            else:
                lines_str = self.index("end-1c").split(".")[0]
                self.configure(height=max(1, int(lines_str)))
        except Exception:
            pass

    def set_markdown(self, md_content: str):
        self.configure(state="normal")
        self.delete("1.0", "end")

        if not md_content:
            self.configure(height=1, state="disabled")
            return

        lines = md_content.splitlines()
        in_code_block = False
        code_lang = "CODE"
        code_lines: list[str] = []

        for line in lines:
            stripped = line.strip()

            # ── Fenced code block ─────────────────────────────────────────
            if stripped.startswith("```"):
                if in_code_block:
                    if code_lines:
                        self.insert("end", "\n".join(code_lines) + "\n", ("code_block",))
                        code_lines = []
                    self.insert("end", "─" * 44 + "\n", ("code_footer",))
                    in_code_block = False
                else:
                    in_code_block = True
                    lang_hint = stripped[3:].strip().upper()
                    code_lang = lang_hint if lang_hint else "CODE"
                    self.insert("end", f"  {code_lang}\n", ("code_header",))
                continue

            if in_code_block:
                code_lines.append(line)
                continue

            # ── Headings ──────────────────────────────────────────────────
            if stripped.startswith("### "):
                self.insert("end", fix_arabic(stripped[4:]) + "\n", ("h3",))
                continue
            elif stripped.startswith("## "):
                self.insert("end", fix_arabic(stripped[3:]) + "\n", ("h2",))
                continue
            elif stripped.startswith("# "):
                self.insert("end", fix_arabic(stripped[2:]) + "\n", ("h1",))
                continue

            # ── Dividers ─────────────────────────────────────────────────
            if stripped in ("---", "***", "___", "- - -", "* * *"):
                self.insert("end", "─" * 50 + "\n", ("divider",))
                continue

            # ── Blockquotes ───────────────────────────────────────────────
            if stripped.startswith("> "):
                self.insert("end", fix_arabic(stripped[2:]) + "\n", ("quote",))
                continue

            # ── Bullets & checklists ──────────────────────────────────────
            is_unordered = stripped.startswith(("- ", "* "))
            is_ordered   = len(stripped) > 2 and stripped[0].isdigit() and stripped[1] == "."
            if is_unordered or is_ordered:
                content = stripped[2:] if is_unordered else stripped.split(".", 1)[-1].strip()
                if content.startswith(("[x]", "[X]")):
                    self.insert("end", "☑ ", ("bullet", "checkbox_checked"))
                    self._insert_inline(content[3:].strip(), ("bullet",))
                elif content.startswith("[ ]"):
                    self.insert("end", "☐ ", ("bullet", "checkbox_empty"))
                    self._insert_inline(content[3:].strip(), ("bullet",))
                else:
                    self.insert("end", "· ", ("bullet_dot",))
                    self._insert_inline(content, ("bullet",))
                self.insert("end", "\n")
                continue

            # ── Regular paragraph ─────────────────────────────────────────
            self._insert_inline(line, ())
            self.insert("end", "\n")

        # Flush unclosed code block
        if code_lines:
            self.insert("end", "\n".join(code_lines) + "\n", ("code_block",))
            self.insert("end", "─" * 44 + "\n", ("code_footer",))

        try:
            self.update_idletasks()
            self._recalculate_height()
        except Exception:
            pass

        self.configure(state="disabled")

    def _insert_inline(self, text: str, base_tags: tuple):
        if not text:
            return

        pattern = r"(\*\*[^*]+\*\*|__[^_]+__|`[^`]+`|\*[^*]+\*|_[^_]+_)"
        tokens = re.split(pattern, text)
        for tok in tokens:
            if not tok:
                continue

            if (tok.startswith("**") and tok.endswith("**") and len(tok) > 4) or \
               (tok.startswith("__") and tok.endswith("__") and len(tok) > 4):
                self.insert("end", fix_arabic(tok[2:-2]), base_tags + ("bold",))

            elif tok.startswith("`") and tok.endswith("`") and len(tok) > 2:
                self.insert("end", f" {tok[1:-1]} ", base_tags + ("code_inline",))

            elif (tok.startswith("*") and tok.endswith("*") and len(tok) > 2) or \
                 (tok.startswith("_") and tok.endswith("_") and len(tok) > 2):
                self.insert("end", fix_arabic(tok[1:-1]), base_tags + ("italic",))

            else:
                self.insert("end", fix_arabic(tok), base_tags)

    # ── Back-compat alias ─────────────────────────────────────────────────────
    def _insert_inline_tokens(self, text: str, base_tags: tuple):
        self._insert_inline(text, base_tags)
