from langchain_core.tools import tool
from langgraph.runtime import get_runtime

from ...runtime.runtime_config import RuntimeConfig
from ....common.network import HttpClient
from ...model.knowledge_base import KBResult, KBQueryRequest


def create_knowledge_base_query_tool():
    """创建知识库查询工具"""
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
        context = get_runtime().context
        response = HttpClient.post_response(
            url=runtime_config.http_request.url,
            response_type=KBResult,
            headers=runtime_config.http_request.headers,
            json=KBQueryRequest(
                kb_list=context.resources.kb_list,
                query=query
                ).model_dump(),
        )
        return response.data
    
    return knowledge_base_query
