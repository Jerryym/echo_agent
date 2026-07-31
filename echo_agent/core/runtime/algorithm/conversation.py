from ...model import Message, Role


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
