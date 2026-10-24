"""Data models and type definitions for Antigravity Chat Manager."""

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ToolExecution:
    name: str
    action_type: str
    input_data: dict[str, Any] = field(default_factory=dict)
    output_data: Optional[str] = None
    exit_code: Optional[int] = None
    duration_ms: Optional[int] = None
    diff: Optional[str] = None
    summary: Optional[str] = None


@dataclass
class ConversationMessage:
    role: str  # "user", "assistant", "system", "tool"
    content: str
    timestamp: Optional[str] = None
    model: Optional[str] = None
    thinking: Optional[str] = None
    thinking_duration: Optional[str] = None
    stop_reason: Optional[str] = None
    tools: list[ToolExecution] = field(default_factory=list)


@dataclass
class ConversationSummary:
    id: str
    title: str
    preview: str
    step_count: int
    created_time: Optional[str] = None
    last_modified_time: Optional[str] = None
    workspace: Optional[str] = None
    source: str = "disk"  # "api" or "disk"
    model: Optional[str] = None
    app_target: str = "ide"  # "ide", "v2", or "both"


@dataclass
class LanguageServerEndpoint:
    pid: int
    port: int
    csrf_token: str
    workspace_id: Optional[str] = None
    app_data_dir: Optional[str] = None

    @property
    def is_ide(self) -> bool:
        return self.app_data_dir == "antigravity-ide"

    @property
    def is_v2(self) -> bool:
        return self.app_data_dir == "antigravity"

    @property
    def app_name(self) -> str:
        if self.is_v2:
            return "Antigravity 2.0"
        return "Antigravity IDE"
