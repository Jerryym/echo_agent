from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.base import BaseStore
from pydantic import BaseModel


class RuntimeConfig(BaseModel):
    """
    Runtime 配置

    参数：
        checkpointer: 持久化能力
        store: 跨 thread 数据存储能力
    """
    checkpointer: BaseCheckpointSaver | None = None
    store: BaseStore | None = None