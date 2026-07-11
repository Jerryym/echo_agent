import json
from typing import Any

from langchain_core.messages import BaseMessage
from pydantic import BaseModel


def _to_jsonable(value: Any) -> Any:
    """Recursively convert values into JSON-serializable structures."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, BaseModel):
        return _to_jsonable(value.model_dump())
    if isinstance(value, BaseMessage):
        payload: dict[str, Any] = {
            "type": type(value).__name__,
            "content": _to_jsonable(value.content),
        }
        tool_calls = getattr(value, "tool_calls", None)
        if tool_calls:
            payload["tool_calls"] = _to_jsonable(tool_calls)
        tool_call_id = getattr(value, "tool_call_id", None)
        if tool_call_id:
            payload["tool_call_id"] = tool_call_id
        return payload
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
