from abc import ABC, abstractmethod

from .schema import SandboxConfig, SandboxRunTimeConfig, ExecutionResult


class BaseSandbox(ABC):
    """
    Sandbox 抽象基类
    """
    def __init__(self, config: SandboxConfig) -> None:
        self._config = config # 配置
        self._runtime_config: SandboxRunTimeConfig | None = None # 运行时配置

    @property
    def config(self) -> SandboxConfig:
        """Sandbox 配置"""
        return self._config

    @property
    def runtime_config(self) -> SandboxRunTimeConfig | None:
        """Sandbox 运行时配置"""
        return self._runtime_config

    @abstractmethod
    async def create(self, config: SandboxConfig) -> SandboxRunTimeConfig:
        """创建 Sandbox"""
        pass

    @abstractmethod
    async def execute(
        self,
        sandbox_id: str,
        command: str,
        args: list[str] | None = None,
    ) -> ExecutionResult:
        """
        在 Sandbox 中执行命令。

        签名暂按文档占位，后续 Task 再深入设计。
        """
        pass

    @abstractmethod
    async def destroy(self, runtime_config: SandboxRunTimeConfig) -> None:
        """销毁 Sandbox"""
        pass
