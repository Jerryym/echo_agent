
import asyncio
from itertools import islice

from langgraph.func import entrypoint
from langgraph.pregel import Pregel

from .....common import get_logger
from ....llm import LLMClient
from ....tool.tool_result_reader import ToolResultReader
from ....tool.tool_result_store import ToolResultStore
from .schema import (
    ToolResultAnalyseResult,
    ToolResultTaskState,
)
from .tasks import (
    create_analyse_chunk_task,
    create_plan_task,
)


logger = get_logger("tool_result_workflow")

# Tool Result 分析工作流最大并发数
TOOL_RESULT_ANALYSE_MAX_CONCURRENCY = 8


def create_tool_result_analyse_workflow(llm_client: LLMClient) -> Pregel:
    """创建 Tool Result 分析与规划工作流"""
     # 创建 Plan Task
    plan_task = create_plan_task(llm_client=llm_client)
    # 创建 Chunk Analyse Task
    analyse_chunk_task = create_analyse_chunk_task(llm_client=llm_client)

    tool_result_store = ToolResultStore()
    tool_result_reader = ToolResultReader()

    @entrypoint()
    async def workflow(input: ToolResultTaskState) -> ToolResultAnalyseResult:
        """按计划读取并分析限定数量的工具结果 Chunk"""
        if not input.requirement.strip():
            raise ValueError("requirement must not be empty")

        # 生成本轮数据分析计划
        plan = await plan_task(input)
        requirement = plan.analysis_requirement.strip()
        if not requirement:
            raise ValueError("analysis_requirement must not be empty")

        # 恢复工具结果
        tool_result = tool_result_store.get(input.result_item)
        # 从当前任务进度继续读取
        chunks = tool_result_reader.read(tool_result, offset=input.offset)

        contents: list[str] = []
        next_offset = input.offset
        completed = False
        remaining = plan.max_chunks
        while remaining > 0:
            batch_size = min(remaining, TOOL_RESULT_ANALYSE_MAX_CONCURRENCY)
            batch = list(islice(chunks, batch_size))
            if not batch:
                completed = True
                break

            # 并行分析当前批次
            analyses = await asyncio.gather(
                *[
                    analyse_chunk_task(
                        requirement,
                        chunk,
                    )
                    for chunk in batch
                ]
            )

            # 按 Chunk 顺序保留分析内容
            contents.extend(
                analysis.content
                for analysis in analyses
                if analysis.content.strip()
            )

            # 成功处理本批次后推进进度
            next_offset = batch[-1].next_offset
            remaining -= len(batch)

            # EOF 由 Reader 决定
            completed = batch[-1].eof

            if completed:
                break

        return ToolResultAnalyseResult(
            content="\n".join(contents),
            completed=completed,
            next_offset=next_offset,
            next_action=plan.next_action,
        )

    return workflow
