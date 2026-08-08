from ....prompt import PromptLoader
from ...llm.llm_client import LLMClient
from ...model.conversation import ConversationSummary
from ...model.message import Message, Role


def trim_conversation(messages: list[Message], max_rounds: int = 6) -> list[Message]:
    """
    裁剪对话上下文

    规则：
        1. System 消息始终保留。
        2. User 消息表示一轮开始。
        3. 每轮包含该 User 消息到下一条 User 消息之前的所有消息。
        4. 保留最近 rounds 轮。
        5. 返回展开后的消息列表。
    
    参数：
        messages：消息列表
        max_rounds：最大对话轮次
    
    返回：
        裁剪后的消息列表
    """
    if not messages:
        return []

    if max_rounds <= 0:
        return [
            message
            for message in messages
            if message.role == Role.SYSTEM
        ]
    
    system_messages: list[Message] = [] # 系统提示词列表
    conversation_rounds: list[list[Message]] = [] # 对话轮次列表，每个轮次包含一个HumanMessage和多个AIMessage + ToolMessage
    current_round: list[Message] | None = None # 当前对话轮次，包含一个HumanMessage和多个AIMessage + ToolMessage

    for message in messages:
        match message.role:
            case Role.SYSTEM:
                system_messages.append(message)
            case Role.USER:
                if current_round is not None:
                    conversation_rounds.append(current_round)
                current_round = [message]
            case _:
                if current_round is not None:
                    current_round.append(message)

    if current_round is not None:
        conversation_rounds.append(current_round)

    return system_messages + [
        message
        for conversation_round in conversation_rounds[-max_rounds:]
        for message in conversation_round
    ]


class ConversationCompressor:
    """
    对话压缩器：对给定消息片段做结构化摘要。
    """
    def __init__(self, llm_client: LLMClient):
        self._llm_client = llm_client
        self._policy = PromptLoader.load("prompt/conversation_summary_policy.md")

    def compress(self, messages: list[Message], prior_summary: ConversationSummary | None = None) -> ConversationSummary:
        """
        压缩对话
        """
        payload = self._build_user_payload(messages, prior_summary)
        result = self._llm_client.invoke_structured(
            schema=ConversationSummary,
            prompt=self._policy,
            user_input=payload,
            context=None,       # 不注入 agent/skill prompt
            agent_prompt=None,
            strict=True,
        )
        summary = result.structured
        if not isinstance(summary, ConversationSummary):
            raise TypeError("ConversationSummary structured output expected")
        return summary

    async def acompress(self, messages: list[Message], prior_summary: ConversationSummary | None = None) -> ConversationSummary:
        """
        异步压缩对话
        """
        payload = self._build_user_payload(messages, prior_summary)
        result = await self._llm_client.ainvoke_structured(
            schema=ConversationSummary,
            prompt=self._policy,
            user_input=payload,
            context=None,
            agent_prompt=None,
            strict=True,
        )
        summary = result.structured
        if not isinstance(summary, ConversationSummary):
            raise TypeError("ConversationSummary structured output expected")
        return summary

    @staticmethod
    def render(summary: ConversationSummary) -> str:
        """将结构化摘要渲染为可注入下一轮的文本（组装层用）。"""
        def bullets(items: list[str]) -> str:
            return "\n".join(f"- {x}" for x in items) if items else "- (none)"
        return (
            "[Conversation Summary]\n"
            f"Goal: {summary.user_goal}\n"
            f"Context:\n{bullets(summary.context)}\n"
            f"Decisions:\n{bullets(summary.decisions)}\n"
            f"Completed:\n{bullets(summary.completed_tasks)}\n"
            f"Pending:\n{bullets(summary.pending_tasks)}\n"
            f"Constraints:\n{bullets(summary.constraints)}\n"
            f"Facts:\n{bullets(summary.important_facts)}"
        )

    def _build_user_payload(self, messages: list[Message], prior_summary: ConversationSummary | None) -> str:
        """
        构建用户输入
        """
        lines = []
        for message in messages:
            if message.role == Role.SYSTEM:
                continue
            text = message.content if isinstance(message.content, str) else str(message.content)
            if not (text or "").strip():
                continue
            lines.append(f"[{message.role.value}] {text}")
        prior = (
            prior_summary.model_dump_json(indent=2)
            if prior_summary is not None
            else "(none)"
        )
        return (
            "## Prior Summary\n"
            f"{prior}\n\n"
            "## Messages To Compress\n"
            + ("\n".join(lines) if lines else "(empty)")
        )

