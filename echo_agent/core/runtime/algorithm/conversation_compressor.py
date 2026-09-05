from ....common import get_logger
from ....prompt import PromptLoader
from ...llm import LLMClient, LLMConfig
from ...model.conversation import ConversationState, ConversationSummary
from ...model.message import Message, Role
from ...model.token_usage import TokenUsage

logger = get_logger("ConversationCompressor")


class ConversationCompressor:
    """
    对话压缩工作流
    """
    # 对话压缩默认触发阈值
    DEFAULT_TRIGGER_RATIO = 0.7

    def __init__(self, llm_config: LLMConfig, max_context_tokens: int, keep_rounds: int = 4, trigger_ratio: float = DEFAULT_TRIGGER_RATIO):
        if max_context_tokens <= 0:
            raise ValueError("max_tokens must be greater than 0")
        if keep_rounds <= 0:
            raise ValueError("keep_rounds must be greater than 0")
        if not 0 < trigger_ratio < 1:
            raise ValueError("trigger_ratio must be between 0 and 1")
        
        self._llm_client = LLMClient(llm_config)
        self._prompt = PromptLoader.load("prompt/conversation_summary_policy.md")
        self._max_context_tokens = max_context_tokens # 最大上下文长度
        self._keep_rounds = keep_rounds # 保留的对话轮次
        self._trigger_ratio = trigger_ratio

    def compress(self, conversation: ConversationState, token_usage: TokenUsage) -> bool:
        """压缩对话"""
        if not self._should_compress(token_usage):
            return False

        # 拆分对话
        rounds = self._split_rounds(conversation.messages)
        if len(rounds) <= self._keep_rounds:
            return False
        compressed_messages, retained_messages = self._select_messages(rounds)
        
        # 生成会话摘要
        summary = self._summarize_conversation(compressed_messages, conversation.summary)

        conversation.summary = summary
        conversation.messages = retained_messages

        logger.info(f"Conversation compressed. {conversation.summary.render()}")

        return True

    async def acompress(self, conversation: ConversationState, token_usage: TokenUsage) -> bool:
        """压缩对话（异步）"""
        if not self._should_compress(token_usage):
            return False
        
        # 拆分对话
        rounds = self._split_rounds(conversation.messages)
        if len(rounds) <= self._keep_rounds:
            return False
        compressed_messages, retained_messages = self._select_messages(rounds)

        # 生成会话摘要
        summary = await self._asummarize_conversation(compressed_messages, conversation.summary)

        conversation.summary = summary
        conversation.messages = retained_messages

        logger.info(f"Conversation compressed. {conversation.summary.render()}")

        return True

    def _get_trigger_tokens(self) -> int:
        """获取触发压缩的token数量"""
        return int(self._max_context_tokens * self._trigger_ratio)

    def _should_compress(self, token_usage: TokenUsage) -> bool:
        """判断是否需要压缩对话"""
        return token_usage.total_tokens >= self._get_trigger_tokens()

    def _select_messages(self, rounds: list[list[Message]]) -> tuple[list[Message], list[Message]]:
        compress_rounds = rounds[:-self._keep_rounds]
        retain_remaining = rounds[-self._keep_rounds:]
        return (
            self._flatten_rounds(compress_rounds),
            self._flatten_rounds(retain_remaining),
        )

    def _summarize_conversation(self, messages: list[Message], prior_summary: ConversationSummary | None = None) -> ConversationSummary:
        """生成会话摘要"""
        payload = self._build_user_payload(messages, prior_summary)
        result = self._llm_client.invoke_structured(
            schema=ConversationSummary,
            prompt=self._prompt,
            user_input=payload,
        )
        summary = ConversationSummary.model_validate(result.structured)
        return summary

    async def _asummarize_conversation(self, messages: list[Message], prior_summary: ConversationSummary | None = None) -> ConversationSummary:
        """生成会话摘要（异步）"""
        payload = self._build_user_payload(messages, prior_summary)
        result = await self._llm_client.ainvoke_structured(
            schema=ConversationSummary,
            prompt=self._prompt,
            user_input=payload,
        )
        summary = ConversationSummary.model_validate(result.structured)
        return summary

    @staticmethod
    def _build_user_payload(messages: list[Message], prior_summary: ConversationSummary | None) -> str:
        """构建用户输入"""
        lines = [
            f"[{m.role.value}] {m.content}"
            for m in messages
            if (m.content or "").strip()
        ]
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

    @staticmethod
    def _split_rounds(messages: list[Message]) -> list[list[Message]]:
        """将对话消息拆分为若干轮次"""
        rounds: list[list[Message]] = []
        current_round: list[Message] | None = None

        for message in messages:
            if message.role == Role.USER:
                if current_round is not None:
                    rounds.append(current_round)
                current_round = [message]
                continue

            if current_round is not None:
                current_round.append(message)

        if current_round is not None:
            rounds.append(current_round)

        return rounds

    @staticmethod
    def _flatten_rounds(rounds: list[list[Message]]) -> list[Message]:
        return [
            message
            for round_messages in rounds
            for message in round_messages
        ]
