from ....common import get_logger
from ....prompt import PromptLoader
from ...llm import ContextBudgetGateway, LLMClient, LLMConfig
from ...model.context import CompactedContext, ContextState
from ...model.message import Message, Role
from ...model.token_usage import TokenUsage

logger = get_logger("ContextCompactor")


class ContextCompactor:
    """
    上下文压缩器
    """
    SUMMARY_PREFIX = "[Compacted Context]\n"
    MAX_COMPACTION_ATTEMPTS = 3

    def __init__(self, llm_config: LLMConfig, retain_recent_tokens: int = 32_000) -> None:
        if retain_recent_tokens <= 0:
            raise ValueError("retain_recent_tokens must be greater than 0")

        self._llm_client = LLMClient(llm_config)
        self._retain_recent_tokens = retain_recent_tokens
        self._prompt = PromptLoader.load("prompt/context_compaction.md")
        self._user_input = (
            "Build a complete updated compacted context from the history. "
            "Existing compacted-context messages are prior summaries. "
            "Older user messages may be removed after compaction. "
            "Preserve their still-valid goals, constraints, preferences and facts."
        )

    def compress(self, context: ContextState) -> tuple[ContextState, TokenUsage]:
        """同步压缩"""
        target, retain_budget = self._compression_budget(context)
        usage = TokenUsage()
        for attempt in range(self.MAX_COMPACTION_ATTEMPTS):
            budget = 0 if attempt == self.MAX_COMPACTION_ATTEMPTS - 1 else retain_budget
            selected = self._select_messages(context.messages, budget)
            if selected is None:
                if ContextBudgetGateway.calculate_tokens(context.messages) <= target:
                    return context.model_copy(deep=True), usage
                raise ValueError("No compressible messages can satisfy the context target")
            source_messages, retained_messages = selected
            result = self._llm_client.invoke_structured(
                schema=CompactedContext,
                prompt=self._prompt,
                user_input=self._build_instruction(target, retained_messages),
                history=source_messages,
            )
            usage = usage.add(result.token_usage)
            if result.structured is None:
                raise ValueError("Context compaction returned no structured output")
            compacted = CompactedContext.model_validate(result.structured)
            candidate = self._build_context(context, compacted, retained_messages)
            if ContextBudgetGateway.calculate_tokens(candidate.messages) <= target:
                return candidate, usage
            retain_budget //= 2
        raise ValueError(f"Context compaction did not reach target_tokens={target}")

    async def acompress(self, context: ContextState) -> tuple[ContextState, TokenUsage]:
        """异步压缩"""
        target, retain_budget = self._compression_budget(context)
        usage = TokenUsage()
        for attempt in range(self.MAX_COMPACTION_ATTEMPTS):
            budget = 0 if attempt == self.MAX_COMPACTION_ATTEMPTS - 1 else retain_budget
            selected = self._select_messages(context.messages, budget)
            if selected is None:
                if ContextBudgetGateway.calculate_tokens(context.messages) <= target:
                    return context.model_copy(deep=True), usage
                raise ValueError("No compressible messages can satisfy the context target")
            source_messages, retained_messages = selected
            result = await self._llm_client.ainvoke_structured(
                schema=CompactedContext,
                prompt=self._prompt,
                user_input=self._build_instruction(target, retained_messages),
                history=source_messages,
            )
            usage = usage.add(result.token_usage)
            if result.structured is None:
                raise ValueError("Context compaction returned no structured output")
            compacted = CompactedContext.model_validate(result.structured)
            candidate = self._build_context(context, compacted, retained_messages)
            if ContextBudgetGateway.calculate_tokens(candidate.messages) <= target:
                return candidate, usage
            retain_budget //= 2
        raise ValueError(f"Context compaction did not reach target_tokens={target}")

    def should_compact(self, context: ContextState) -> bool:
        """是否需要压缩上下文"""
        tokens = ContextBudgetGateway.calculate_tokens(context.messages)
        return tokens >= context.auto_compact_threshold or tokens > context.context_window

    def _compression_budget(self, context: ContextState) -> tuple[int, int]:
        target = min(context.auto_compact_threshold - 1, context.context_window)
        _, protected = self._select_messages(context.messages, 0) or ([], context.messages)
        minimum = self._build_context(context, CompactedContext(), protected)
        minimum_tokens = ContextBudgetGateway.calculate_tokens(minimum.messages)
        if minimum_tokens > target:
            raise ValueError(
                "Protected messages and summary structure exceed context target: "
                f"minimum_tokens={minimum_tokens}, target_tokens={target}"
            )
        summary_tokens = ContextBudgetGateway.calculate_tokens(
            self._build_context(context, CompactedContext(), []).messages
        )
        return target, min(self._retain_recent_tokens, target - summary_tokens)

    def _build_instruction(self, target: int, retained: list[Message]) -> str:
        retained_tokens = ContextBudgetGateway.calculate_tokens(retained)
        return (
            f"{self._user_input}\n"
            f"The summary message has an estimated budget of at most "
            f"{max(0, target - retained_tokens)} tokens, including its JSON fields "
            "and marker. Use shorter phrases and omit nonessential details."
        )

    def _select_messages(self, messages: list[Message], retain_budget: int | None = None) -> tuple[list[Message], list[Message]] | None:
        """选择消息"""
        budget = self._retain_recent_tokens if retain_budget is None else retain_budget
        groups, protected_tail = self._group_messages(messages)
        latest_user = next(
            (message for message in reversed(messages) if message.role == Role.USER),
            None,
        )
        protected_indices = {
            index for index, group in enumerate(groups)
            if any(message is latest_user for message in group)
        }
        retained_indices = set(protected_indices)

        def retained_messages(indices: set[int]) -> list[Message]:
            return [
                message for index, group in enumerate(groups)
                if index in indices for message in group
            ] + list(protected_tail)

        # 用户消息与执行消息一起计算，旧摘要始终进入压缩材料
        for index in range(len(groups) - 1, -1, -1):
            if index in protected_indices or any(self._is_summary(m) for m in groups[index]):
                continue
            candidate_indices = retained_indices | {index}
            if ContextBudgetGateway.calculate_tokens(retained_messages(candidate_indices)) > budget:
                break
            retained_indices = candidate_indices

        source = [
            message for index, group in enumerate(groups)
            if index not in retained_indices for message in group
        ]
        if not source:
            return None
        return source, retained_messages(retained_indices)

    @classmethod
    def _build_context(cls, context: ContextState, compacted: CompactedContext, retained_messages: list[Message],) -> ContextState:
        """构建压缩后的上下文状态"""
        summary_message = Message(
            role=Role.SYSTEM,
            content=cls.SUMMARY_PREFIX + compacted.model_dump_json(indent=2),
        )
        candidate = context.model_copy(deep=True)
        candidate.messages = [
            summary_message,
            *[
                message.model_copy(deep=True)
                for message in retained_messages
            ],
        ]
        return candidate

    @classmethod
    def _is_summary(cls, message: Message) -> bool:
        return (
            message.role == Role.SYSTEM
            and isinstance(message.content, str)
            and message.content.startswith(cls.SUMMARY_PREFIX)
        )

    @staticmethod
    def _group_messages(messages: list[Message]) -> tuple[list[list[Message]], list[Message]]:
        """
        按工具调用关系对消息分组

        返回：
            groups: 已闭合的完整消息组
            protected_tail: 无法安全分组的消息尾部

        原则：
            1. 普通消息独立成组
            2. Assistant Tool Call 与对应的 Tool Result 合并成组，遇到不完整或异常关联时，保护异常位置及后续消息
        """
        groups: list[list[Message]] = []
        index = 0

        while index < len(messages):
            message = messages[index]

            # 孤立的 Tool Result
            if message.role == Role.TOOL:
                return groups, messages[index:]

            # 普通消息独立成组
            if message.role != Role.ASSISTANT or not message.tool_calls:
                groups.append([message])
                index += 1
                continue

            # Assistant Tool Call
            expected_ids = {
                call.tool_call_id
                for call in message.tool_calls
            }

            # 无效或重复的 Tool Call ID
            if (
                not all(
                    call.tool_call_id
                    for call in message.tool_calls
                )
                or len(expected_ids) != len(message.tool_calls)
            ):
                return groups, messages[index:]

            group = [message]
            received_ids: set[str] = set()
            next_index = index + 1

            # 收集连续的 Tool Result
            while (next_index < len(messages) and messages[next_index].role == Role.TOOL):
                tool_message = messages[next_index]
                tool_id = tool_message.tool_call_id

                if (tool_id not in expected_ids or tool_id in received_ids):
                    return groups, messages[index:]

                if tool_id is not None:
                    received_ids.add(tool_id)

                group.append(tool_message)
                next_index += 1

            # Tool Call 尚未全部完成
            if received_ids != expected_ids:
                return groups, messages[index:]

            groups.append(group)
            index = next_index

        return groups, []
