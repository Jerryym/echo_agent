from uuid import UUID

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QMainWindow, QSplitter, QWidget

from case import register_all
from case.base import CaseResult
from case.env_config import build_config, load_console_env
from manager.case_registry import CaseRegistry
from manager.case_worker import CaseWorker
from manager.console_logger import logger
from manager.session_manager import SessionManager
from ui.panel import ChatPanel, LogPanel, SessionPanel
from ui.widget import ControlBar


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        load_console_env()
        self._llm_config = None
        self._runtimes: dict[tuple[UUID, str], object] = {}
        self._worker: CaseWorker | None = None
        self._worker_session_id: UUID | None = None
        self._init_window()
        self._init_ui()
        self._bind_events()
        self.session_panel.create_session()

    def _init_window(self):
        self.setWindowTitle("Echo Agent Console")
        self.resize(1600, 900)

    def _init_ui(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # case registry
        self.case_registry = CaseRegistry()
        register_all(self.case_registry)

        # 菜单栏
        self.control_bar = ControlBar(self.case_registry)
        layout.addWidget(self.control_bar)

        splitter = QSplitter(Qt.Horizontal)
        # session panel
        self.session_manager = SessionManager()
        self.session_panel = SessionPanel(self.session_manager)
        splitter.addWidget(self.session_panel)
        # chat panel
        self.chat_panel = ChatPanel()
        splitter.addWidget(self.chat_panel)
        # log panel
        self.log_panel = LogPanel()
        splitter.addWidget(self.log_panel)

        # 设置分割器大小
        splitter.setSizes([300, 800, 500])
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 5)
        splitter.setStretchFactor(2, 3)
        layout.addWidget(splitter)

        self.setCentralWidget(root)

    def _bind_events(self):
        logger.logged.connect(self.log_panel.append)
        self.session_panel.session_created.connect(self._on_session_switched)
        self.session_panel.session_changed.connect(self._on_session_switched)
        self.chat_panel.message_sent.connect(self._on_message_sent)
        self.chat_panel.hitl_submitted.connect(self._on_hitl_submitted)
        self.chat_panel.hitl_cancelled.connect(self._on_hitl_cancelled)
        self.control_bar.case_changed.connect(self._on_case_changed)

    def _on_session_switched(self, session) -> None:
        self.chat_panel.set_session(session)
        # 切到非运行中会话时恢复输入；运行中会话保持 busy
        if self._worker_session_id is None or session.id != self._worker_session_id:
            if not self.chat_panel.hitl_form.isVisible():
                self.chat_panel.set_busy(False)

    def _get_llm_config(self):
        if self._llm_config is None:
            self._llm_config = build_config()
        return self._llm_config

    def _current_handler(self):
        case_name = self.control_bar.current_case_name()
        if not case_name:
            return None
        return self.case_registry.get(case_name).handler

    def _get_or_create_runtime(self, session_id: UUID, case_name: str):
        key = (session_id, case_name)
        if key not in self._runtimes:
            handler = self.case_registry.get(case_name).handler
            needs_llm = case_name != "hitl"
            llm_config = self._get_llm_config() if needs_llm else None
            self._runtimes[key] = handler.create_runtime(llm_config)
            logger.trace(f"runtime created: case={case_name} session={session_id}")
        return self._runtimes[key]

    def _is_busy(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def _start_worker(
        self,
        *,
        handler,
        runtime,
        session_id: str,
        mode: str,
        payload,
    ) -> None:
        if self._is_busy():
            logger.warn("Agent 仍在运行，请稍候")
            return

        self.chat_panel.set_busy(True)
        self._worker_session_id = UUID(str(session_id))

        self._worker = CaseWorker(
            handler=handler,
            runtime=runtime,
            session_id=session_id,
            mode=mode,
            payload=payload,
            parent=self,
        )
        self._worker.finished_ok.connect(self._on_worker_finished)
        self._worker.failed.connect(self._on_worker_failed)
        self._worker.finished.connect(self._on_worker_thread_finished)
        self._worker.start()

    def _on_worker_finished(self, result: object) -> None:
        # 已切换到其他会话则丢弃过期结果
        current = self.session_manager.current_session
        if (
            current is None
            or self._worker_session_id is None
            or current.id != self._worker_session_id
        ):
            logger.warn("忽略过期 Agent 结果（会话已切换）")
            return
        if isinstance(result, CaseResult):
            self._apply_result(result)

    def _on_worker_failed(self, message: str) -> None:
        logger.error(f"case invoke failed: {message}")

    def _on_worker_thread_finished(self) -> None:
        # HITL 弹出时保持输入禁用；否则恢复
        if not self.chat_panel.hitl_form.isVisible():
            self.chat_panel.set_busy(False)
        self._worker = None
        self._worker_session_id = None

    def _apply_result(self, result: CaseResult) -> None:
        if result.debug:
            logger.trace(result.debug)
        if result.pending_hitl is not None:
            logger.warn(f"HITL pending: type={result.pending_hitl.get('type')}")
            self.chat_panel.show_hitl(result.pending_hitl)
            return
        if result.reply:
            self.chat_panel.add_assistant_message(result.reply, tokens=0)
            logger.info(f"assistant: {result.reply[:200]}")

    def _on_message_sent(self, text: str) -> None:
        # 先更新 UI，再后台跑 Agent
        self.chat_panel.add_user_message(text)
        logger.info(f"user message: {text}")

        session = self.session_manager.current_session
        if session is None:
            logger.error("请先新建会话")
            return

        handler = self._current_handler()
        if handler is None:
            logger.error("未选择 Test Case")
            return

        try:
            runtime = self._get_or_create_runtime(session.id, handler.name)
        except Exception as exc:
            logger.error(f"runtime create failed: {exc}")
            return

        self._start_worker(
            handler=handler,
            runtime=runtime,
            session_id=str(session.id),
            mode="message",
            payload=text,
        )

    def _on_hitl_submitted(self, values: dict) -> None:
        session = self.session_manager.current_session
        if session is None:
            logger.error("HITL resume 失败：无会话")
            self.chat_panel.set_busy(False)
            return

        handler = self._current_handler()
        if handler is None:
            logger.error("HITL resume 失败：未选择 Case")
            self.chat_panel.set_busy(False)
            return

        try:
            runtime = self._get_or_create_runtime(session.id, handler.name)
        except Exception as exc:
            logger.error(f"runtime create failed: {exc}")
            self.chat_panel.set_busy(False)
            return

        logger.info(f"HITL resume: {values}")
        self._start_worker(
            handler=handler,
            runtime=runtime,
            session_id=str(session.id),
            mode="hitl",
            payload=values,
        )

    def _on_hitl_cancelled(self) -> None:
        """INPUT 取消：resume {"cancelled": true}，驱动 HITL status=cancelled。"""
        logger.warn("HITL cancelled by user")
        session = self.session_manager.current_session
        if session is None:
            logger.error("HITL cancel resume 失败：无会话")
            self.chat_panel.set_busy(False)
            return

        handler = self._current_handler()
        if handler is None:
            logger.error("HITL cancel resume 失败：未选择 Case")
            self.chat_panel.set_busy(False)
            return

        try:
            runtime = self._get_or_create_runtime(session.id, handler.name)
        except Exception as exc:
            logger.error(f"runtime create failed: {exc}")
            self.chat_panel.set_busy(False)
            return

        payload = {"cancelled": True}
        logger.info(f"HITL cancel resume: {payload}")
        self._start_worker(
            handler=handler,
            runtime=runtime,
            session_id=str(session.id),
            mode="hitl",
            payload=payload,
        )

    def _on_case_changed(self, case_name: str) -> None:
        logger.info(f"test case switched: {case_name}")
