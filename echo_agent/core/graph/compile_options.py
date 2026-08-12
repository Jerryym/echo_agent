from dataclasses import dataclass

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.base import BaseStore


@dataclass
class GraphCompileOptions:
    """
    图编译选项

    参数：
        checkpointer: 持久化能力
        store: 跨 thread 数据存储能力
    """
    checkpointer: BaseCheckpointSaver | None = None
    store: BaseStore | None = None
