from ...common import get_logger
from ..model.agent import AgentMode
from ..runtime.gateway import BaseGateWay
from .exception import ToolAuthorizationError
from .schema import ToolDefinition

logger = get_logger("tool")


class ToolGateWay(BaseGateWay):
    """
    工具网关：根据 AgentMode 和 Tool Annotations 判断工具是否允许调用
    """
    def __init__(self) -> None:
        super().__init__()

    def authorize(self, tool: ToolDefinition, mode: AgentMode) -> None:
        """
        授权检查

        授权规则：
            - readOnlyHint:
                - ASK 模式关注该字段。
                - True：表示工具为只读工具，可用于 ASK 模式。
                - False：表示工具可能产生修改，不允许用于 ASK 模式。
                - None：未提供只读行为提示，由模式策略决定。
            - destructiveHint:
                - AGENT 模式关注该字段。
                - True：表示工具具有破坏性操作能力，允许 AGENT 模式调用。
                - False：表示工具不具有破坏性操作能力，不代表其一定为只读工具。
                - None：未提供破坏性行为提示，由模式策略决定。
            - idempotentHint:
                - 用于描述工具调用是否具有幂等性。
                - 不直接作为 ASK / AGENT 模式的授权依据。
                - None：表示未提供幂等性提示。
            - openWorldHint:
                - AGENT 模式下，如果为 True，表示工具可能产生开放世界副作用，调用前需要进入 Human-in-the-Loop 流程。
                - False：表示工具不会产生开放世界副作用。
                - None：未提供开放世界行为提示，由相关策略决定。
        """
        if mode == AgentMode.AGENT:
            return

        if mode == AgentMode.ASK:
            self._authorize_ask_mode(tool)
            return

        raise ToolAuthorizationError(
            f"unsupported agent mode: {mode}"
        )

    def filter(self, tools: list[ToolDefinition], mode: AgentMode) -> list[ToolDefinition]:
        """
        过滤工具
        """
        available_tools: list[ToolDefinition] = []
        for tool in tools:
            try:
                self.authorize(tool, mode)
            except ToolAuthorizationError:
                logger.debug("filter tool | blocked=%s mode=%s", tool.name, mode)
                continue
            available_tools.append(tool)
        return available_tools

    
    def _authorize_ask_mode(self, tool: ToolDefinition) -> None:
        """
        检查 Ask 模式下的工具权限
        """
        annotations = tool.annotations
        logger.debug("authorize_ask_mode | tool=%s annotations=%s", tool.name, annotations)

        if annotations is None:
            raise ToolAuthorizationError(
                f"tool '{tool.name}' is not allowed in ask mode: "
                "annotations are missing"
            )

        # 如果 readOnlyHint 为 False，则不允许调用
        if annotations.read_only_hint is not True:
            raise ToolAuthorizationError(
                f"tool '{tool.name}' is not allowed in ask mode: "
                "readOnlyHint is not true"
            )
