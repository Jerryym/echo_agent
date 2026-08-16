class ToolError(Exception):
    """
    Tool 基础异常
    """
    def __init__(self, message: str, tool_name: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.tool_name = tool_name

    def __str__(self) -> str:
        if self.tool_name:
            return f"[{self.tool_name}] {self.message}"
        return self.message


class ToolNotFoundError(ToolError):
    """
    工具不存在
    """
    pass


class ToolAuthorizationError(ToolError):
    """
    工具授权失败
    """
    pass


class ToolExecutionError(ToolError):
    """
    工具执行失败
    """
    pass


class ToolApprovalRequiredError(ToolAuthorizationError):
    """
    工具执行需要人工审批
    """
    pass