from collections.abc import Awaitable, Callable

from langgraph.func import task
from langgraph.runtime import get_runtime

from .....prompt import PromptLoader
from .....utils import update_agent_result
from ....llm import LLMClient
from ....model.tool import ToolResultChunk
from ....runtime import RuntimeConfig
from .schema import ToolResultAnalyseDecision, ToolResultChunkAnalysis


# Chunk 分析提示词
TOOL_RESULT_CHUNK_ANALYSE_PROMPT = PromptLoader.load("core/capability/workflow/tool_result/prompt/chunk_analyse.md")
# 批次级分析决策提示词
TOOL_RESULT_ANALYSE_DECISION_PROMPT = PromptLoader.load("core/capability/workflow/tool_result/prompt/decide.md")

AnalyseChunkCallable = Callable[[str, ToolResultChunk], Awaitable[ToolResultChunkAnalysis]]
DecideCallable = Callable[[str, str, list[ToolResultChunkAnalysis], bool], Awaitable[ToolResultAnalyseDecision]]

def create_analyse_chunk_task(llm_client: LLMClient) -> AnalyseChunkCallable:
    """创建 Tool Result Chunk 分析任务"""

    @task
    async def analyse_chunk(requirement: str, chunk: ToolResultChunk) -> ToolResultChunkAnalysis:
        """提取当前 Chunk 中与分析需求相关的信息"""
        if not requirement.strip():
            raise ValueError("requirement must not be empty")

        if not chunk.content:
            return ToolResultChunkAnalysis(content="")

        runtime = get_runtime()
        runtime_config = RuntimeConfig.get_runtime_config()
        response = await llm_client.ainvoke_structured(
            schema=ToolResultChunkAnalysis,
            prompt=TOOL_RESULT_CHUNK_ANALYSE_PROMPT,
            user_input={
                "requirement": requirement,
                "chunk_content": chunk.content,
                "chunk_offset": chunk.offset,
                "chunk_next_offset": chunk.next_offset,
            },
            context=runtime.context,
            agent_resources=runtime.context.resources,
            config=runtime_config.to_llm_runnable_config(),
        )

        result = ToolResultChunkAnalysis.model_validate(response.structured)
        update_agent_result(runtime.context, response.reasoning or "",response.token_usage)
        return result
    
    return analyse_chunk


def create_decide_task(llm_client: LLMClient,) -> DecideCallable:
    """创建 Tool Result 批次级分析决策任务"""

    @task
    async def decide(requirement: str, accumulated_content: str, batch_analyses: list[ToolResultChunkAnalysis], eof: bool) -> ToolResultAnalyseDecision:
        """整合累计信息并判断是否满足分析需求"""
        if not requirement.strip():
            raise ValueError("requirement must not be empty")

        runtime = get_runtime()
        runtime_config = RuntimeConfig.get_runtime_config()
        response = await llm_client.ainvoke_structured(
            schema=ToolResultAnalyseDecision,
            prompt=TOOL_RESULT_ANALYSE_DECISION_PROMPT,
            user_input={
                "requirement": requirement,
                "accumulated_content": accumulated_content,
                "batch_analyses": [
                    analysis.model_dump(mode="json")
                    for analysis in batch_analyses
                ],
                "eof": eof,
            },
            context=runtime.context,
            agent_resources=runtime.context.resources,
            config=runtime_config.to_llm_runnable_config(),
        )

        result = ToolResultAnalyseDecision.model_validate(response.structured)
        update_agent_result(runtime.context, response.reasoning or "",response.token_usage)
        return result

    return decide
