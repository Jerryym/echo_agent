from uuid import uuid4

from pydantic import BaseModel

from ...model.workflow import WorkflowTask


class WorkflowTaskBuilder:
    """
    工作流任务生成器
    """
    @staticmethod
    def build(state: BaseModel) -> WorkflowTask:
        task = WorkflowTask(task_id=uuid4().hex)
        task.update(state)
        return task
