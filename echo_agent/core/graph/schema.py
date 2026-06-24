from pydantic import BaseModel


class BaseInput(BaseModel):
    """
    Graph 输入模型
    """
    pass


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