from langgraph.func import entrypoint

from ....graph.schema import BaseContext
from ....llm import LLMClient
from .schema import ToolArtifactAnalyseInput, ToolArtifactAnalyseResult
from .tasks import create_analyse_artifact_chunk_task, read_artifact_chunk


def create_tool_artifact_analyse_workflow(llm_client: LLMClient):
    """创建 Tool Artifact 分析工作流。"""
    analyse_artifact_chunk = (create_analyse_artifact_chunk_task(llm_client))

    @entrypoint(context_schema=BaseContext)
    async def tool_artifact_analyse_workflow(input: ToolArtifactAnalyseInput) -> ToolArtifactAnalyseResult:
        """Tool Artifact 分析工作流"""
        # 读取 Tool Artifact 内容块
        chunk = await read_artifact_chunk(input.tool_call_id,input.offset,)
        if not chunk.content:
            return ToolArtifactAnalyseResult(
                content="",
                next_offset=chunk.next_offset,
                completed=chunk.eof,
            )
    
        # 分析 Tool Artifact 内容块
        analysis = await analyse_artifact_chunk(input.requirement,chunk)
        return ToolArtifactAnalyseResult(
            content=analysis.content,
            next_offset=chunk.next_offset,
            completed=chunk.eof,
        )

    return tool_artifact_analyse_workflow