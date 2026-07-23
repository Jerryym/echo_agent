from manager.case_registry import CaseInfo, CaseRegistry

from case.agent_case import AgentCase
from case.hitl_case import HITLCase
from case.llm_client_case import LLMClientCase
from case.react_agent_case import ReactAgentCase
from case.react_agent_hitl_case import ReactAgentHITLCase
from case.react_agent_hitl_mcp_case import ReactAgentHITLMCPCase
from case.react_agent_mcp_case import ReactAgentMCPCase


CASES = [
    LLMClientCase(),
    AgentCase(),
    ReactAgentCase(),
    ReactAgentHITLCase(),
    ReactAgentMCPCase(),
    ReactAgentHITLMCPCase(),
    HITLCase(),
]


def register_all(registry: CaseRegistry) -> None:
    for case in CASES:
        registry.register(
            CaseInfo(
                name=case.name,
                title=case.title,
                handler=case,
            )
        )
