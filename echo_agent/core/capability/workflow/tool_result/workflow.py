
import asyncio
from itertools import islice

from langgraph.func import entrypoint
from langgraph.pregel import Pregel

from ....llm import LLMClient
from ....tool.tool_result_reader import ToolResultReader
from ....tool.tool_result_store import ToolResultStore
from .schema import (
    ToolResultAnalyseInput,
    ToolResultAnalyseResult,
)
from .tasks import (
    create_analyse_chunk_task,
    create_decide_task,
)


# Tool Result 分析工作流最大并发数
TOOL_RESULT_ANALYSE_MAX_CONCURRENCY = 4


def create_tool_result_analyse_workflow(llm_client: LLMClient) -> Pregel:
    """创建 Tool Result 分析工作流"""
    # 创建 Chunk 分析任务
    analyse_chunk_task = create_analyse_chunk_task(llm_client=llm_client)
    # 创建分析决策任务
    decide_task = create_decide_task(llm_client=llm_client)

    tool_result_store = ToolResultStore()
    tool_result_reader = ToolResultReader()

    @entrypoint()
    async def workflow(input: ToolResultAnalyseInput) -> ToolResultAnalyseResult:
        """按需读取工具结果，并进行批次级分析与决策"""
        requirement = input.requirement.strip()
        if not requirement:
            raise ValueError("requirement must not be empty")

        # 恢复完整工具执行结果
        tool_result = tool_result_store.get(input.result_item)
        # 生成按需读取的 Chunk 迭代器
        chunks = tool_result_reader.read(tool_result)

        accumulated_content = ""
        completed = False

        while True:
            # 每轮仅消费最多 4 个 Chunk
            batch = list(islice(chunks, TOOL_RESULT_ANALYSE_MAX_CONCURRENCY))
            if not batch:
                completed = True
                break

            # EOF 由 Reader 决定，不交给 LLM 推断
            eof = batch[-1].eof

            # 同一批次的 Chunk Analyse Tasks 并行执行
            futures = [
                analyse_chunk_task(requirement, chunk)
                for chunk in batch
            ]

            batch_analyses = await asyncio.gather(*futures)

            # 综合历史累计信息和当前批次分析结果，
            # 判断是否已经满足分析需求。
            decision = await decide_task(
                requirement,
                accumulated_content,
                list(batch_analyses),
                eof,
            )

            accumulated_content = decision.content
            completed = eof

            # 信息充分或数据全部遍历，结束工作流。
            if decision.sufficient or completed:
                break

        return ToolResultAnalyseResult(
            content=accumulated_content,
            completed=completed,
        )

    return workflow
