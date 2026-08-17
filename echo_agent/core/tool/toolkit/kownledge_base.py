from langchain_core.tools import tool

from ...runtime.runtime_config import RuntimeConfig
from ....common.network import HttpClient
from ...model.knowledge_base import KBResult


@tool
def knowledge_base_query(query: str) -> KBResult:
    """
    Query the knowledge base and return the retrieval result.

    Args:
        query: The query to search for in the knowledge base.

    Returns:
        The knowledge base query result, including the final content
        and the source documents.
    """
    runtime_config = RuntimeConfig.get_runtime_config()
    response = HttpClient.post_response(
        url=runtime_config.http_request.url,
        response_type=KBResult,
        headers=runtime_config.http_request.headers,
        json={"query": query},
    )
    return response.data
