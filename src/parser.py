"""Step parser transforming raw trajectory steps and transcripts into structured messages."""

import json
import re
from typing import Any, Optional

from src.models import ConversationMessage, ToolExecution


def parse_api_trajectory(trajectory: dict[str, Any]) -> list[ConversationMessage]:
    raw_steps = trajectory.get("steps", [])
    gen_metadata = trajectory.get("generatorMetadata", [])
    model_by_idx: dict[int, str] = {}
    for gm in gen_metadata:
        m_raw = gm.get("chatModel")
        m_name = None
        if isinstance(m_raw, dict):
            m_name = m_raw.get("modelDisplayName") or m_raw.get("responseModel") or m_raw.get("model")
        elif isinstance(m_raw, list) and m_raw and isinstance(m_raw[0], dict):
            m_name = m_raw[0].get("modelDisplayName") or m_raw[0].get("responseModel") or m_raw[0].get("model")
        elif isinstance(m_raw, str):
            m_name = m_raw

        if m_name:
            for idx in gm.get("stepIndices", []):
                model_by_idx[idx] = str(m_name)

    messages: list[ConversationMessage] = []

    for i, step in enumerate(raw_steps):
        step_type = step.get("type", "")
        meta = step.get("metadata", {})
        created_at = meta.get("createdAt")
        model_name = model_by_idx.get(i)

        if step_type == "CORTEX_STEP_TYPE_USER_INPUT":
            user_input = step.get("userInput", {})
            raw_text = user_input.get("userResponse", "")
            if not raw_text and "items" in user_input:
                for item in user_input["items"]:
                    if isinstance(item, dict) and "text" in item:
                        raw_text = item["text"]
                        break

            clean_text = _clean_user_prompt(raw_text)
            messages.append(
                ConversationMessage(
                    role="user",
                    content=clean_text,
                    timestamp=created_at,
                )
            )

        elif step_type == "CORTEX_STEP_TYPE_PLANNER_RESPONSE":
            pr = step.get("plannerResponse", {})
            text = pr.get("response", "")
            thinking = pr.get("thinking")
            thinking_raw = pr.get("thinkingDuration")
            duration_str = None
            if thinking_raw:
                t_str = str(thinking_raw).strip()
                if t_str.endswith("s"):
                    try:
                        val = float(t_str[:-1])
                        duration_str = f"{val:.1f}s"
                    except ValueError:
                        duration_str = t_str
                else:
                    try:
                        val = float(t_str)
                        duration_str = f"{val / 1000:.1f}s" if val > 50 else f"{val:.1f}s"
                    except ValueError:
                        duration_str = t_str
            stop_reason = pr.get("stopReason")

            tools: list[ToolExecution] = []
            for tc in pr.get("toolCalls", []):
                t_name = tc.get("toolName", tc.get("name", "tool"))
                args = tc.get("arguments", tc.get("args", {}))
                tools.append(
                    ToolExecution(
                        name=t_name,
                        action_type=t_name,
                        input_data=args if isinstance(args, dict) else {},
                        summary=tc.get("toolSummary", tc.get("summary")),
                    )
                )

            messages.append(
                ConversationMessage(
                    role="assistant",
                    content=text,
                    timestamp=created_at,
                    model=model_name,
                    thinking=thinking,
                    thinking_duration=duration_str,
                    stop_reason=stop_reason,
                    tools=tools,
                )
            )

        elif step_type == "CORTEX_STEP_TYPE_RUN_COMMAND":
            rc = step.get("runCommand", {})
            cmd = rc.get("commandLine", "")
            output = rc.get("combinedOutput", rc.get("output", ""))
            code = rc.get("exitCode")
            tool_item = ToolExecution(
                name="run_command",
                action_type="command",
                input_data={"command": cmd},
                output_data=output,
                exit_code=code,
            )
            _attach_tool_to_last_assistant(messages, tool_item, created_at)

        elif step_type == "CORTEX_STEP_TYPE_CODE_ACTION":
            ca = step.get("codeAction", {})
            path = ca.get("filePath", ca.get("path", ""))
            diff = ca.get("diff", "")
            summary = ca.get("description", "Code edit")
            tool_item = ToolExecution(
                name="code_action",
                action_type="edit",
                input_data={"file": path},
                diff=diff,
                summary=summary,
            )
            _attach_tool_to_last_assistant(messages, tool_item, created_at)

        elif step_type == "CORTEX_STEP_TYPE_VIEW_FILE":
            vf = step.get("viewFile", {})
            path = vf.get("absolutePath", vf.get("path", ""))
            content_preview = vf.get("content", "")
            tool_item = ToolExecution(
                name="view_file",
                action_type="view",
                input_data={"file": path},
                output_data=content_preview[:300] if content_preview else None,
                summary=f"View file: {path.rsplit('/', 1)[-1] if '/' in path else path.rsplit('\\\\', 1)[-1]}",
            )
            _attach_tool_to_last_assistant(messages, tool_item, created_at)

        elif step_type == "CORTEX_STEP_TYPE_GREP_SEARCH":
            gs = step.get("grepSearch", {})
            query = gs.get("query", "")
            tool_item = ToolExecution(
                name="grep_search",
                action_type="search",
                input_data={"query": query},
                output_data=str(gs.get("results", ""))[:300],
                summary=f"Grep search: {query}",
            )
            _attach_tool_to_last_assistant(messages, tool_item, created_at)

    return messages


def parse_transcript_records(records: list[dict[str, Any]]) -> list[ConversationMessage]:
    messages: list[ConversationMessage] = []

    for r in records:
        r_type = r.get("type")
        source = r.get("source")
        content = r.get("content", "")
        ts = r.get("timestamp")

        if r_type == "USER_INPUT" or source == "USER_EXPLICIT":
            clean_text = _clean_user_prompt(content)
            messages.append(
                ConversationMessage(
                    role="user",
                    content=clean_text,
                    timestamp=ts,
                )
            )

        elif r_type == "PLANNER_RESPONSE" or source == "MODEL":
            thinking = r.get("thinking")
            tools: list[ToolExecution] = []
            for tc in r.get("tool_calls", []):
                t_name = tc.get("name", "tool")
                args = tc.get("arguments", {})
                tools.append(
                    ToolExecution(
                        name=t_name,
                        action_type=t_name,
                        input_data=args if isinstance(args, dict) else {},
                        summary=tc.get("summary"),
                    )
                )

            messages.append(
                ConversationMessage(
                    role="assistant",
                    content=content,
                    timestamp=ts,
                    thinking=thinking,
                    tools=tools,
                )
            )

        elif r_type in ("TOOL_OUTPUT", "RUN_COMMAND_OUTPUT") or source == "TOOL":
            tool_item = ToolExecution(
                name="tool_result",
                action_type="output",
                output_data=content,
            )
            _attach_tool_to_last_assistant(messages, tool_item, ts)

    return messages


def _attach_tool_to_last_assistant(messages: list[ConversationMessage], tool_item: ToolExecution, timestamp: Optional[str]) -> None:
    if messages and messages[-1].role == "assistant":
        messages[-1].tools.append(tool_item)
    else:
        messages.append(
            ConversationMessage(
                role="assistant",
                content="",
                timestamp=timestamp,
                tools=[tool_item],
            )
        )


def _clean_user_prompt(text: str) -> str:
    if not text:
        return ""
    # Strip <USER_REQUEST> wrappers if present
    text = re.sub(r"^\s*<USER_REQUEST>\s*", "", text)
    text = re.sub(r"\s*</USER_REQUEST>\s*$", "", text)
    return text.strip()
