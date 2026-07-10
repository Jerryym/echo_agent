import json
from typing import Any


def format_debug(value: Any) -> str:
    """Format value for debug output; pretty-print JSON/dict/list content."""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith(("{", "[")):
            try:
                return json.dumps(json.loads(value), ensure_ascii=False, indent=2)
            except json.JSONDecodeError:
                pass
        return value
    return repr(value)


def debug_print_messages(tag: str, messages: list) -> None:
    """Print message history summary for ReAct debug."""
    print(f"{tag} messages count={len(messages)}")
    for i, msg in enumerate(messages):
        cls = type(msg).__name__
        if cls == "ToolMessage":
            print(f"{tag} [{i}] ToolMessage id={msg.tool_call_id}")
            print(format_debug(msg.content))
        elif cls == "AIMessage" and getattr(msg, "tool_calls", None):
            names = [
                tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "?")
                for tc in msg.tool_calls
            ]
            print(f"{tag} [{i}] AIMessage tool_calls={names}")
        else:
            content = format_debug(msg.content)
            preview = content[:200] + ("..." if len(content) > 200 else "")
            print(f"{tag} [{i}] {cls} {preview}")
