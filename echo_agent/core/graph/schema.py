from pydantic import BaseModel

from ..model import UserInput


class BaseInput(BaseModel):
    """
    Graph 输入模型

    参数:
        input: UserInput 用户输入
    """
    input: UserInput


class BaseOutput(BaseModel):
    """
    Graph 输出模型
    """
    pass


class BaseState(BaseModel):
    """
    Graph 状态模型
    """
    pass


class BaseContext(BaseModel):
    """
    Graph 上下文模型
    """
    pass