"""会话压缩编排：触发判断、切片、调用 Compressor、写回 ConversationState。"""

from __future__ import annotations

import math

from ...model.agent import AgentState
from ...model.message import Message, Role
from .conversation_compressor import ConversationCompressor


def split_conversation_rounds(
    messages: list[Message],
) -> tuple[list[Message], list[list[Message]]]:
    """
    将消息拆成 system 列表与对话轮次。

    轮次边界：USER 消息开启新轮；SYSTEM 不进入轮次。
    """
    system_messages: list[Message] = []
    rounds: list[list[Message]] = []
    current: list[Message] | None = None

    for message in messages:
        match message.role:
            case Role.SYSTEM:
                system_messages.append(message)
            case Role.USER:
                if current is not None:
                    rounds.append(current)
                current = [message]
            case _:
                if current is not None:
                    current.append(message)

    if current is not None:
        rounds.append(current)

    return system_messages, rounds


def flatten_rounds(rounds: list[list[Message]]) -> list[Message]:
    return [message for round_messages in rounds for message in round_messages]


def maybe_compress_conversation(
    agent_state: AgentState,
    compressor: ConversationCompressor,
    *,
    max_tokens: int,
    compress_ratio: float = 0.7,
) -> bool:
    """
    若会话 token 达到阈值，压缩「本轮之前」历史的前 compress_ratio 部分。

    不负责：压缩 LLM 的 token 计入会话累计。

    返回:
        是否实际执行了压缩写回。
    """
    if max_tokens <= 0 or agent_state.token_usage.total_tokens < max_tokens:
        return False

    conversation = agent_state.conversation
    system_messages, rounds = split_conversation_rounds(conversation.messages)
    if len(rounds) < 2:
        # 至少需要「历史轮 + 本轮」才有可压内容
        return False

    current_round = rounds[-1]
    prior_rounds = rounds[:-1]
    cut = math.floor(len(prior_rounds) * compress_ratio)
    if cut <= 0:
        return False

    to_compress = flatten_rounds(prior_rounds[:cut])
    retained_prior = flatten_rounds(prior_rounds[cut:])

    try:
        summary = compressor.compress(
            to_compress,
            prior_summary=conversation.summary,
        )
    except Exception:
        return False

    conversation.summary = summary
    conversation.messages = system_messages + retained_prior + current_round
    return True


async def amaybe_compress_conversation(
    agent_state: AgentState,
    compressor: ConversationCompressor,
    *,
    max_tokens: int,
    compress_ratio: float = 0.7,
) -> bool:
    """异步版 maybe_compress_conversation。"""
    if max_tokens <= 0 or agent_state.token_usage.total_tokens < max_tokens:
        return False

    conversation = agent_state.conversation
    system_messages, rounds = split_conversation_rounds(conversation.messages)
    if len(rounds) < 2:
        return False

    current_round = rounds[-1]
    prior_rounds = rounds[:-1]
    cut = math.floor(len(prior_rounds) * compress_ratio)
    if cut <= 0:
        return False

    to_compress = flatten_rounds(prior_rounds[:cut])
    retained_prior = flatten_rounds(prior_rounds[cut:])

    try:
        summary = await compressor.acompress(
            to_compress,
            prior_summary=conversation.summary,
        )
    except Exception:
        return False

    conversation.summary = summary
    conversation.messages = system_messages + retained_prior + current_round
    return True
