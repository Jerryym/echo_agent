from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Sequence

from pydantic import BaseModel

if TYPE_CHECKING:
    from ..core.model import Message


def _to_jsonable(value: Any) -> Any:
    """Recursively convert values into JSON-serializable structures."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, BaseModel):
        return _to_jsonable(value.model_dump())
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(item) for item in value]
    return str(value)


def format_debug(value: Any) -> str:
    """Format value for debug output; pretty-print JSON/dict/list content."""
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith(("{", "[")):
            try:
                return json.dumps(json.loads(value), ensure_ascii=False, indent=2)
            except json.JSONDecodeError:
                pass
        return value

    try:
        return json.dumps(_to_jsonable(value), ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return repr(value)


def debug_print_messages(tag: str, messages: Sequence[Message]) -> None:
    """Print message history summary for ReAct debug."""
    print(f"{tag} messages count={len(messages)}")
    for i, msg in enumerate(messages):
        role = msg.role.value
        if role == "tool":
            print(f"{tag} [{i}] tool id={msg.tool_call_id}")
            print(format_debug(msg.content))
        elif role == "assistant" and msg.tool_calls:
            names = [tool_call.name for tool_call in msg.tool_calls]
            print(f"{tag} [{i}] assistant tool_calls={names}")
        else:
            content = format_debug(msg.content)
            preview = content[:200] + ("..." if len(content) > 200 else "")
            print(f"{tag} [{i}] {role} {preview}")
