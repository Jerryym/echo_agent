from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SandboxType(Enum):
    """
    Sandbox 类型
    """
    MICROSANDBOX = "microsandbox" #microsandbox 


class SandboxStatus(Enum):
    """ 
    Sandbox 状态
    """
    CREATED = "created"    # 已创建
    RUNNING = "running"    # 运行中
    STOPPED = "stopped"    # 已停止
    FAILED = "failed"      # 失败


class SandboxConfig(BaseModel):
    """
    Sandbox 配置

    Attributes:
        type: Sandbox 类型
        name: Sandbox 名称
        image: 镜像
        cpu_limit: Sandbox 最大 CPU 限制
        memory_limit: Sandbox 最大内存限制
        timeout: Sandbox 超时时间
        network_enabled: 是否启用网络
        environment: Sandbox 环境变量
    """
    type: SandboxType = Field(default=SandboxType.MICROSANDBOX)
    name: str | None
    image: str
    cpu_limit: int | None
    memory_limit: int | None
    timeout: int | None
    network_enabled: bool
    environment: dict[str, str] = Field(default_factory=dict)


class SandboxRunTimeConfig(BaseModel):
    """
    Sandbox 运行时配置

    Attributes:
        id: Sandbox ID
        status: 状态
        created_at: 创建时间
        metadata: 运行时元数据
    """
    id: str
    status: SandboxStatus
    created_at: datetime | None = None
    metadata: dict[str, Any]


class ExecutionResult(BaseModel):
    """
    Sandbox 执行结果

    Attributes:
        success: 是否成功
        stdout: 标准输出
        stderr: 标准错误
        exit_code: 退出码
        duration: 执行时间
        metadata: 运行时元数据
    """
    success: bool
    stdout: str
    stderr: str
    exit_code: int | None
    duration: float | None
    metadata: dict[str, Any] = Field(default_factory=dict)
