import json

from langchain_core.messages import HumanMessage
from langgraph.func import entrypoint
from langgraph.pregel import Pregel

from .....utils import ContextUsageCalculator
from ....model.tool import ToolResult
from ....tool.tool_result_reader import ToolResultReader
from ....tool.tool_result_store import ToolResultStore
from .schema import ToolResultReadResult, ToolResultTaskState


MAX_READ_TOKENS = 8192  # 最大读取 Token 数
READ_CHUNK_SIZE = 4096  # 读取块大小


def create_tool_result_read_workflow() -> Pregel:
    """创建工具结果读取工作流"""
    store = ToolResultStore()
    reader = ToolResultReader()

    @entrypoint()
    async def workflow(input: ToolResultTaskState) -> ToolResultReadResult:
        result = store.get(input.result_item)
        chunks = reader.read(result, chunk_size=READ_CHUNK_SIZE, offset=input.offset)

        contents: list[str] = []
        next_offset = input.offset
        eof = False
        for chunk in chunks:
            candidate = "".join([*contents, chunk.content])
            payload = build_read_payload(input.task_id, candidate, chunk.next_offset, chunk.eof)
            try:
                validate_read_budget(payload)
            except ValueError:
                if not contents:
                    raise ValueError("A single read chunk exceeds delivery budget; cannot advance offset") from None
                break
            contents.append(chunk.content)
            next_offset = chunk.next_offset
            eof = chunk.eof
            if eof:
                break

        return ToolResultReadResult(content="".join(contents), next_offset=next_offset, eof=eof)

    return workflow


def build_read_payload(task_id: str, content: str, next_offset: int, eof: bool) -> dict[str, str | int | bool]:
    """构建工具结果读取返回结构"""
    return {
        "task_id": task_id,
        "content": content,
        "next_offset": next_offset,
        "eof": eof,
    }


def validate_read_budget(payload: dict[str, str | int | bool]) -> None:
    """工具结果读取预算校验"""
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    # Token预算
    tokens = ContextUsageCalculator.calculate(messages=[HumanMessage(content=serialized)])
    if tokens > MAX_READ_TOKENS:
        raise ValueError("Tool result read exceeds delivery token budget")

    # 构建Tool Result
    wrapped = ToolResult(
        name="read_tool_result",
        tool_call_id="x" * 128,
        success=True,
        result=payload,
    )
    size = len(wrapped.model_dump_json().encode("utf-8"))
    if size > ToolResultStore.DEFAULT_THRESHOLD - 1024:
        raise ValueError("Read result may be externalized by ToolResultStore")
