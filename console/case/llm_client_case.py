from __future__ import annotations

from dataclasses import dataclass, field

from langchain_core.messages import AIMessage, BaseMessage

from echo_agent import LLMClient, LLMConfig, UserInput

from case.base import BaseCase, CaseResult


@dataclass
class LLMRuntime:
    client: LLMClient
    history: list[BaseMessage] = field(default_factory=list)


class LLMClientCase(BaseCase):
    name = "llm_client"
    title = "LLM Client"
    strategy = "None"

    def create_runtime(self, llm_config: LLMConfig | None) -> LLMRuntime:
        if llm_config is None:
            raise ValueError("LLM Client Case 需要 llm_config")
        return LLMRuntime(client=LLMClient(llm_config))

    def on_message(self, runtime: LLMRuntime, session_id: str, text: str) -> CaseResult:
        result = runtime.client.invoke(
            prompt="You are a helpful assistant. Be concise.",
            user_input=UserInput(text=text),
            history=runtime.history,
        )
        content = result.text if isinstance(result.text, str) else str(result.text)
        runtime.history.append(UserInput(text=text).to_human_message())
        runtime.history.append(AIMessage(content=content))
        return CaseResult(reply=content, debug=f"session={session_id} history={len(runtime.history)}")
