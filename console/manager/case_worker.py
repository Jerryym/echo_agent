from typing import Any, Literal

from PySide6.QtCore import QThread, Signal

from case.base import BaseCase, CaseResult


class CaseWorker(QThread):
    """
    在后台线程执行 Case，避免阻塞 UI。
    """
    finished_ok = Signal(object)  # CaseResult
    failed = Signal(str)

    def __init__(
        self,
        *,
        handler: BaseCase,
        runtime: Any,
        session_id: str,
        mode: Literal["message", "hitl"],
        payload: Any,
        parent=None,
    ):
        super().__init__(parent)
        self._handler = handler
        self._runtime = runtime
        self._session_id = session_id
        self._mode = mode
        self._payload = payload

    def run(self) -> None:
        try:
            if self._mode == "message":
                result = self._handler.on_message(
                    self._runtime,
                    self._session_id,
                    self._payload,
                )
            else:
                result = self._handler.on_hitl(
                    self._runtime,
                    self._session_id,
                    self._payload,
                )
            if not isinstance(result, CaseResult):
                result = CaseResult(reply=str(result))
            self.finished_ok.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))
