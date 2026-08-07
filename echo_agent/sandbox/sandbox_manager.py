from .sandbox import BaseSandbox
from .schema import SandboxConfig, SandboxRunTimeConfig, ExecutionResult
from .sandbox_factory import SandboxFactory


class SandboxManager:
    """
    Sandbox 管理器
    """
    def __init__(self) -> None:
        self._sandboxes: dict[str, BaseSandbox] = {}
        self._runtime_configs: dict[str, SandboxRunTimeConfig] = {}
        self._current_sandbox: BaseSandbox | None = None

    @property
    def current_sandbox(self) -> BaseSandbox | None:
        """当前活跃的 Sandbox（最近一次 create 成功的实例）"""
        return self._current_sandbox

    async def create(self, config: SandboxConfig) -> SandboxRunTimeConfig:
        """
        创建 Sandbox
        """
        sandbox = SandboxFactory.create(config)
        runtime_config = await sandbox.create(config)
        sandbox_id = runtime_config.id
        self._sandboxes[sandbox_id] = sandbox
        self._runtime_configs[sandbox_id] = runtime_config
        self._current_sandbox = sandbox
        return runtime_config

    async def execute(
        self,
        sandbox_id: str,
        command: str,
        args: list[str] | None = None,
    ) -> ExecutionResult:
        """指定 sandbox 执行命令"""
        sandbox = self.get_sandbox(sandbox_id)
        return await sandbox.execute(sandbox_id, command, args)

    async def destroy(self, sandbox_id: str) -> None:
        """销毁 Sandbox 并从 Manager 中移除"""
        sandbox = self.get_sandbox(sandbox_id)
        runtime_config = self._runtime_configs.get(sandbox_id)
        if runtime_config is None:
            raise ValueError(f"Sandbox {sandbox_id} has no runtime config")

        await sandbox.destroy(runtime_config)
        self._sandboxes.pop(sandbox_id, None)
        self._runtime_configs.pop(sandbox_id, None)
        if self._current_sandbox is sandbox:
            self._current_sandbox = None

    def get_sandbox(self, sandbox_id: str) -> BaseSandbox:
        """获取已登记的 Sandbox；不存在则抛出 ValueError。"""
        sandbox = self._sandboxes.get(sandbox_id)
        if sandbox is None:
            raise ValueError(f"Sandbox {sandbox_id} not found")
        return sandbox
