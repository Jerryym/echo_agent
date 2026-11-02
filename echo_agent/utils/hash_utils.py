import hashlib
import json
from typing import Any


def sha256_hex(content: str | dict[str, Any]) -> str:
    if isinstance(content, dict):
        content = canonical_json(content)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
