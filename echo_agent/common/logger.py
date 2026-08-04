from __future__ import annotations

import json
import logging
import os
import sys
import threading
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import TYPE_CHECKING, Any, Sequence

from pydantic import BaseModel

if TYPE_CHECKING:
    from ..core.model import Message

ROOT_LOGGER_NAME = "echoagent"
_DEFAULT_LEVEL = logging.INFO
_BACKUP_COUNT = 30
_DEFAULT_LOG_FILENAME = "echoagent.log"
_ENV_LOG_DIR = "ECHO_AGENT_LOG_DIR"
_ENV_LOG_FILE = "ECHO_AGENT_LOG_FILE"


def user_documents_dir() -> Path:
    """跨平台解析「我的文档 / Documents」目录。"""
    if sys.platform == "win32":
        home = Path.home()
        for name in ("Documents", "文档"):
            candidate = home / name
            if candidate.is_dir():
                return candidate
        profile = os.environ.get("USERPROFILE")
        if profile:
            return Path(profile) / "Documents"
        return home / "Documents"

    if sys.platform == "darwin":
        return Path.home() / "Documents"

    xdg = os.environ.get("XDG_DOCUMENTS_DIR")
    if xdg:
        return Path(xdg)
    docs = Path.home() / "Documents"
    if docs.is_dir():
        return docs
    return Path.home()


def default_log_dir() -> Path:
    """日志目录：Documents/.echoagent/logs。"""
    return user_documents_dir() / ".echoagent" / "logs"


def resolve_log_file(
    *,
    log_dir: str | Path | None = None,
    log_file: str | Path | None = None,
) -> Path:
    """
    解析最终日志文件路径，优先级：
    1. 参数 log_file
    2. 环境变量 ECHO_AGENT_LOG_FILE
    3. 参数 log_dir / echo_agent.log
    4. 环境变量 ECHO_AGENT_LOG_DIR / echo_agent.log
    5. 默认 Documents/.echoagent/logs/echo_agent.log
    """
    if log_file is not None:
        return Path(log_file).expanduser().resolve()

    env_file = os.environ.get(_ENV_LOG_FILE)
    if env_file:
        return Path(env_file).expanduser().resolve()

    if log_dir is not None:
        return (Path(log_dir).expanduser().resolve() / _DEFAULT_LOG_FILENAME)

    env_dir = os.environ.get(_ENV_LOG_DIR)
    if env_dir:
        return (Path(env_dir).expanduser().resolve() / _DEFAULT_LOG_FILENAME)

    return default_log_dir() / _DEFAULT_LOG_FILENAME


def _to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, BaseModel):
        return _to_jsonable(value.model_dump())
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(item) for item in value]
    return str(value)


def format_value(value: Any) -> str:
    """将任意值格式化为可读字符串，便于日志输出。"""
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


class Logger:
    """
    echo_agent 日志单例：配置根 logger「echo_agent」的控制台与按日滚动文件 handler。

    子模块通过 get_logger(\"react\") 取得 logging.getLogger(\"echo_agent.react\")，
    便于按模块过滤；子 logger 向上传播到已配置 handler 的根 logger。

    自定义路径请优先调用 configure_logging(...)，或设置环境变量
    ECHO_AGENT_LOG_DIR / ECHO_AGENT_LOG_FILE。
    """

    _instance: Logger | None = None
    _lock = threading.Lock()

    def __new__(cls) -> Logger:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._initialized = False
                    cls._instance = inst
        return cls._instance

    def __init__(
        self,
        *,
        level: int = _DEFAULT_LEVEL,
        log_dir: str | Path | None = None,
        log_file: str | Path | None = None,
        also_console: bool = True,
        backup_count: int = _BACKUP_COUNT,
    ) -> None:
        if getattr(self, "_initialized", False):
            return
        self._apply_config(
            level=level,
            log_dir=log_dir,
            log_file=log_file,
            also_console=also_console,
            backup_count=backup_count,
        )

    def _apply_config(
        self,
        *,
        level: int = _DEFAULT_LEVEL,
        log_dir: str | Path | None = None,
        log_file: str | Path | None = None,
        also_console: bool = True,
        backup_count: int = _BACKUP_COUNT,
    ) -> None:
        resolved = resolve_log_file(log_dir=log_dir, log_file=log_file)
        self._log_file = resolved
        self._log_dir = resolved.parent
        self._log_dir.mkdir(parents=True, exist_ok=True)

        root = logging.getLogger(ROOT_LOGGER_NAME)
        root.setLevel(level)
        for handler in list(root.handlers):
            handler.close()
        root.handlers.clear()
        root.propagate = False

        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        file_handler = TimedRotatingFileHandler(
            filename=str(self._log_file),
            when="midnight",
            interval=1,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.suffix = "%Y-%m-%d"
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

        if also_console:
            console = logging.StreamHandler()
            console.setFormatter(formatter)
            root.addHandler(console)

        self._root = root
        self._initialized = True

    def reconfigure(
        self,
        *,
        level: int = _DEFAULT_LEVEL,
        log_dir: str | Path | None = None,
        log_file: str | Path | None = None,
        also_console: bool = True,
        backup_count: int = _BACKUP_COUNT,
    ) -> None:
        """重新配置日志路径与 handlers（即使已初始化也会覆盖）。"""
        with self._lock:
            self._apply_config(
                level=level,
                log_dir=log_dir,
                log_file=log_file,
                also_console=also_console,
                backup_count=backup_count,
            )

    @property
    def log_dir(self) -> Path:
        return self._log_dir

    @property
    def log_file(self) -> Path:
        return self._log_file

    @property
    def root(self) -> logging.Logger:
        return self._root


def configure_logging(
    *,
    log_dir: str | Path | None = None,
    log_file: str | Path | None = None,
    level: int = _DEFAULT_LEVEL,
    also_console: bool = True,
    backup_count: int = _BACKUP_COUNT,
) -> Logger:
    """
    配置（或重新配置）文件日志路径。

    Args:
        log_dir: 日志目录；实际文件为 ``{log_dir}/echo_agent.log``。
        log_file: 完整日志文件路径；优先于 log_dir。
        level: 根 logger 级别。
        also_console: 是否同时输出到控制台。
        backup_count: 按日滚动保留份数。

    也可通过环境变量设置（参数优先）：
        ECHO_AGENT_LOG_FILE / ECHO_AGENT_LOG_DIR
    """
    logger = Logger.__new__(Logger)
    logger.reconfigure(
        level=level,
        log_dir=log_dir,
        log_file=log_file,
        also_console=also_console,
        backup_count=backup_count,
    )
    return logger


def _ensure_configured() -> Logger:
    return Logger()


def get_logger(name: str | None = None) -> logging.Logger:
    """
    获取 echo_agent 命名空间下的 logger（自动初始化单例配置）。

    - get_logger() -> echo_agent
    - get_logger(\"react\") -> echo_agent.react
    - get_logger(\"echo_agent.react\") -> echo_agent.react
    """
    _ensure_configured()
    if not name:
        return logging.getLogger(ROOT_LOGGER_NAME)
    if name == ROOT_LOGGER_NAME or name.startswith(f"{ROOT_LOGGER_NAME}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{name}")


def log_messages(
    logger: logging.Logger,
    tag: str,
    messages: Sequence[Message],
    *,
    level: int = logging.DEBUG,
) -> None:
    """输出消息历史摘要（原 debug_print_messages）。"""
    logger.log(level, "%s messages count=%s", tag, len(messages))
    for i, msg in enumerate(messages):
        role = msg.role.value
        if role == "tool":
            logger.log(level, "%s [%s] tool id=%s", tag, i, msg.tool_call_id)
            logger.log(level, "%s", format_value(msg.content))
        elif role == "assistant" and msg.tool_calls:
            names = [tool_call.name for tool_call in msg.tool_calls]
            logger.log(level, "%s [%s] assistant tool_calls=%s", tag, i, names)
        else:
            content = format_value(msg.content)
            preview = content[:200] + ("..." if len(content) > 200 else "")
            logger.log(level, "%s [%s] %s %s", tag, i, role, preview)
