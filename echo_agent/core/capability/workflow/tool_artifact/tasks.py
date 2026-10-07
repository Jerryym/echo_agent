import codecs

from langgraph.func import task
from langgraph.runtime import get_runtime

from .....utils import update_agent_result
from ....llm import LLMClient
from ....runtime import RuntimeConfig
from .schema import ToolArtifactChunk, ToolArtifactChunkAnalysis


# 内容块大小
ARTIFACT_CHUNK_SIZE = 16 * 1024

# 提示词
TOOL_ARTIFACT_CHUNK_ANALYSE_PROMPT = """
Analyse the provided artifact chunk according to the requirement.

Rules:
- Extract only information supported by the chunk.
- Preserve identifiers, values, field names, and row structure.
- Do not infer information that is not present.
- When the requirement asks for data export, preserve the source data instead of summarising it.
- Return empty content when the chunk contains no relevant information.
"""


@task
def read_artifact_chunk(tool_call_id: str, offset: int) -> ToolArtifactChunk:
    """按固定字节大小读取 Tool Artifact 内容块"""
    if offset < 0:
        raise ValueError("offset must be greater than or equal to 0")

    context = get_runtime().context
    artifact = context.tool_artifacts.get(tool_call_id)
    if artifact is None:
        raise ValueError(f"Tool artifact not found: {tool_call_id}")

    if not artifact.path.exists():
        raise FileNotFoundError(f"Tool artifact file not found: {artifact.path}")

    if not artifact.path.is_file():
        raise ValueError(f"Tool artifact path is not a file: {artifact.path}")

    if offset > artifact.size:
        raise ValueError("offset must not exceed artifact size")

    with artifact.path.open("rb") as file:
        file.seek(offset)
        data = file.read(ARTIFACT_CHUNK_SIZE)
        reached_eof = file.tell() >= artifact.size

    decoder = codecs.getincrementaldecoder("utf-8")()

    if reached_eof:
        content = decoder.decode(data, final=True)
        consumed = len(data)
    else:
        content = decoder.decode(data, final=False)
        pending, _ = decoder.getstate()
        consumed = len(data) - len(pending)

    next_offset = offset + consumed

    return ToolArtifactChunk(
        content=content,
        offset=offset,
        next_offset=next_offset,
        eof=next_offset >= artifact.size,
    )


def create_analyse_artifact_chunk_task(llm_client: LLMClient):
    @task
    async def analyse_artifact_chunk(requirement: str, chunk: ToolArtifactChunk) -> ToolArtifactChunkAnalysis:
        """根据需求分析一个 Tool Artifact 内容块"""
        if not requirement.strip():
            raise ValueError("requirement must not be empty")

        if not chunk.content:
            return ToolArtifactChunkAnalysis(content="")

        runtime = get_runtime()
        runtime_config = RuntimeConfig.get_runtime_config()

        response = await llm_client.ainvoke_structured(
            schema=ToolArtifactChunkAnalysis,
            prompt=TOOL_ARTIFACT_CHUNK_ANALYSE_PROMPT,
            user_input={
                "requirement": requirement,
                "artifact_content": chunk.content,
            },
            context=runtime.context,
            agent_resources=runtime.context.resources,
            config=runtime_config.to_llm_runnable_config(),
        )

        result = ToolArtifactChunkAnalysis.model_validate(
            response.structured
        )

        update_agent_result(
            runtime.context,
            response.reasoning or "",
            response.token_usage,
        )
        return result

    return analyse_artifact_chunk