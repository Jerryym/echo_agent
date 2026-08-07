from .schema import SandboxConfig, SandboxType
from .sandbox import BaseSandbox
from .sandbox_micro import MicroSandbox


class SandboxFactory:

    @staticmethod
    def create(config: SandboxConfig) -> BaseSandbox:
        """创建 Sandbox"""
        if config.type == SandboxType.MICROSANDBOX:
            return MicroSandbox(config) # 创建 microsandbox
        else:
            raise ValueError(f"Invalid sandbox type: {config.type}")
