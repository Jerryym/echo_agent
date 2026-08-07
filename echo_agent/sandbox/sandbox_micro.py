from .sandbox import BaseSandbox
from .schema import SandboxConfig, SandboxRunTimeConfig, ExecutionResult


class MicroSandbox(BaseSandbox):
    """
    MicroSandbox
    """
    def __init__(self, config: SandboxConfig) -> None:
        super().__init__(config)

    async def create(self, config: SandboxConfig) -> SandboxRunTimeConfig:
        pass

    async def execute(self, sandbox_id: str, command: str, args: list[str] | None = None) -> ExecutionResult:
        pass

    async def destroy(self, runtime_config: SandboxRunTimeConfig) -> None:
        pass
