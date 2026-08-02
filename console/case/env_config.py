import json
import os
from pathlib import Path

from dotenv import load_dotenv

from echo_agent import LLMConfig


def load_console_env() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    load_dotenv(env_path)


def env_bool(key: str, default: bool = False) -> bool:
    value = os.getenv(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_json_env(key: str, default):
    raw = os.getenv(key)
    if raw is None or not raw.strip():
        return default
    return json.loads(raw)


def build_config() -> LLMConfig:
    output_version = os.getenv("OUTPUT_VERSION")
    return LLMConfig(
        base_url=os.getenv("BASE_URL"),
        api_key=os.getenv("API_KEY"),
        model_name=os.getenv("MODEL_NAME"),
        model_provider=os.getenv("MODEL_PROVIDER", "openai"),
        temperature=float(os.getenv("TEMPERATURE", 0.2)),
        max_tokens=int(os.getenv("MAX_TOKENS", 512)),
        timeout=int(os.getenv("TIMEOUT", 60)),
        max_retries=int(os.getenv("MAX_RETRIES", 2)),
        use_responses_api=env_bool("USE_RESPONSES_API", False),
        output_version=output_version or None,
        builtin_tools=parse_json_env("BUILTIN_TOOLS", []),
        extra_body=parse_json_env("EXTRA_BODY", {}),
    )


def placeholder_config() -> LLMConfig:
    """HITL-only 等场景的占位配置（不发起真实模型请求）。"""
    return LLMConfig(
        base_url="http://localhost",
        api_key="unused",
        model_name="unused",
    )
