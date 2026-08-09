from langchain_core.messages import ToolCall

from ..core.model.tool import ToolCall as ModelToolCall


class ToolAdapter:
    """
    工具适配器
    """
    @staticmethod
    def to_langchain_tool_call(tool: ModelToolCall) -> ToolCall:
        """
        转换为 LangChain 工具调用
        """
        return ToolCall(name=tool.name, args=tool.args, id=tool.tool_call_id)

    @staticmethod
    def to_langchain_tool_calls(tools: list[ModelToolCall]) -> list[ToolCall]:
        """
        转换为 LangChain 工具调用列表
        """
        return [ToolAdapter.to_langchain_tool_call(tool) for tool in tools]

    @staticmethod
    def to_model_tool_call(tool: ToolCall) -> ModelToolCall:
        """
        转换为模型工具调用
        """
        return ModelToolCall(
            name=tool["name"],
            args=tool.get("args", {}),
            tool_call_id=tool["id"],
        )

    @staticmethod
    def to_model_tool_calls(tools: list[ToolCall]) -> list[ModelToolCall]:
        """
        转换为模型工具调用列表
        """
        return [ToolAdapter.to_model_tool_call(tool) for tool in tools]
