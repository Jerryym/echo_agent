from pydantic import BaseModel, Field

from .token_usage import TokenUsage


class AgentResult(BaseModel):
    """
    Agent运行结果

    参数:
        text: Agent 最终输出文本
        reasoning: Agent 运行时中间思考过程文本
        token_usage: 本轮对话的词元消耗
    """
    text: str = Field(default="")
    reasoning: list[str] = Field(default_factory=list)
    token_usage: TokenUsage = Field(default_factory=TokenUsage)

    def apply_llm_result(self, content: str, token_usage: TokenUsage) -> None:
        """将一次 LLM 调用的思考内容与词元用量写入本轮 AgentResult。"""
        self.token_usage = self.token_usage.add(token_usage)
        if content:
            self.reasoning.append(content)
