from collections.abc import Awaitable, Callable

from langgraph.func import task
from langgraph.runtime import get_runtime

from .....prompt import PromptLoader
from .....utils import update_agent_result
from ....llm import LLMClient
from ....model.tool import ToolResultChunk
from ....runtime import RuntimeConfig
from .schema import (
    ToolResultChunkAnalysis,
    ToolResultPlan,
    ToolResultTaskState,
)

# 工作流规划提示词
TOOL_RESULT_PLAN_PROMPT = PromptLoader.load("core/capability/workflow/tool_result/prompt/plan.md")
# Chunk 分析提示词
TOOL_RESULT_CHUNK_ANALYSE_PROMPT = PromptLoader.load("core/capability/workflow/tool_result/prompt/chunk_analyse.md")

PlanCallable = Callable[[ToolResultTaskState], Awaitable[ToolResultPlan]]
AnalyseChunkCallable = Callable[[str, ToolResultChunk], Awaitable[ToolResultChunkAnalysis]]


def create_plan_task(llm_client: LLMClient) -> PlanCallable:
    """创建 Tool Result 规划任务"""

    @task
    async def plan(state: ToolResultTaskState) -> ToolResultPlan:
        """根据任务目标和已有进度制定本轮执行计划"""
        if not state.requirement.strip():
            raise ValueError("requirement must not be empty")

        runtime = get_runtime()
        runtime_config = RuntimeConfig.get_runtime_config()
        response = await llm_client.ainvoke_structured(
            schema=ToolResultPlan,
            prompt=TOOL_RESULT_PLAN_PROMPT,
            user_input={
                "requirement": state.requirement,
                "result_item": state.result_item.model_dump(mode="json"),
                "offset": state.offset,
                "accumulated_content": state.accumulated_content,
            },
            context=runtime.context,
            agent_resources=runtime.context.resources,
            config=runtime_config.to_llm_runnable_config(),
        )

        result = ToolResultPlan.model_validate(response.structured)
        update_agent_result(runtime.context, response.reasoning or "",response.token_usage)
        return result

    return plan


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
