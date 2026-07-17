from manager.case_registry import CaseInfo, CaseRegistry

from case.agent_case import AgentCase
from case.hitl_case import HITLCase
from case.llm_client_case import LLMClientCase
from case.react_agent_case import ReactAgentCase
from case.react_agent_hitl_case import ReactAgentHITLCase


CASES = [
    LLMClientCase(),
    AgentCase(),
    ReactAgentCase(),
    ReactAgentHITLCase(),
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
