import asyncio
from typing import Awaitable, Callable, TypeAlias

from langgraph.func import entrypoint

from ....graph.schema import BaseContext
from ....llm import LLMClient
from .schema import ToolArtifactAnalyseInput, ToolArtifactAnalyseResult, ToolArtifactChunk, ToolArtifactChunkAnalysis
from .tasks import create_analyse_artifact_chunk_task, read_artifact_chunk


# Tool Artifact 分析工作流最大并发数
ARTIFACT_ANALYSE_MAX_CONCURRENCY = 4
# Tool Artifact 块分析任务
AnalyseChunkCallable: TypeAlias = Callable[[str, ToolArtifactChunk], Awaitable[ToolArtifactChunkAnalysis]]


def create_tool_artifact_analyse_workflow(llm_client: LLMClient):
    """创建 Tool Artifact 分析工作流"""
    analyse_artifact_chunk = (create_analyse_artifact_chunk_task(llm_client))

    @entrypoint(context_schema=BaseContext)
    async def tool_artifact_analyse_workflow(input: ToolArtifactAnalyseInput) -> ToolArtifactAnalyseResult:
        """Tool Artifact 分析工作流"""
        # 创建并发信号量
        semaphore = asyncio.Semaphore(ARTIFACT_ANALYSE_MAX_CONCURRENCY)
        # 保存各内容块的分析结果
        results: list[ToolArtifactChunkAnalysis] = []
        # 从输入指定的字节偏移量开始读取
        offset = input.offset
        completed = False

        while not completed:
            # 当前批次待分析的内容块
            chunks: list[ToolArtifactChunk] = []

            # 每批最多读取 ARTIFACT_ANALYSE_MAX_CONCURRENCY 个内容块
            for _ in range(ARTIFACT_ANALYSE_MAX_CONCURRENCY):
                chunk = await read_artifact_chunk(input.tool_call_id,offset,)

                # 非空内容块调用 LLM 分析
                if chunk.content:
                    chunks.append(chunk)

                # 到达文件末尾，结束后续分块读取
                if chunk.eof:
                    completed = True
                    offset = chunk.next_offset
                    break

                # 防止读取位置未前进导致无限循环
                if chunk.next_offset <= offset:
                    raise RuntimeError("Artifact chunk reader made no progress")

                offset = chunk.next_offset

            # 并发分析当前批次的所有内容块
            # gather 按任务提交顺序返回结果，保证原始内容顺序
            analyses = await asyncio.gather(
                *(
                    analyse(
                        chunk,
                        input.requirement,
                        analyse_artifact_chunk,
                        semaphore,
                    )
                    for chunk in chunks
                )
            )

            # 汇总当前批次的分析结果
            results.extend(analyses)

        # 按原始内容块顺序合并非空分析结果
        content = "\n".join(
            result.content
            for result in results
            if result.content
        )

        # 所有内容块分析成功后返回完整结果
        return ToolArtifactAnalyseResult(
            content=content,
            next_offset=offset,
            completed=True,
        )

    return tool_artifact_analyse_workflow


async def analyse(chunk: ToolArtifactChunk,requirement: str, analyse_chunk: AnalyseChunkCallable, semaphore: asyncio.Semaphore) -> ToolArtifactChunkAnalysis:
    """分析单个 Tool Artifact 内容块，并限制并发数量"""
    async with semaphore:
        return await analyse_chunk(requirement, chunk)
