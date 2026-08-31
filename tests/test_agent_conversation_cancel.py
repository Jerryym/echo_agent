"""结算轮次写入 conversation；Cancel 回滚不丢已结算历史。"""

from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.runtime import Runtime

from echo_agent import Agent, AgentConfig, BaseContext, BaseState, LLMConfig, Node, UserInput
from echo_agent.core.graph import END_NODE, START_NODE, GraphCompileOptions, GraphSchema
from echo_agent.core.model.message import Role


class _State(BaseState):
    pass


class _ReplyNode(Node):
    def __init__(self, name: str, response: str):
        super().__init__(name)
        self._response = response

    def run(self, state: BaseState, runtime: Runtime[BaseContext]) -> dict:
        del state, runtime
        return {"response": self._response}

    async def arun(self, state: BaseState, runtime: Runtime[BaseContext]) -> dict:
        return self.run(state, runtime)


def _llm() -> LLMConfig:
    return LLMConfig(base_url="http://localhost/v1", api_key="k", model_name="m")


def _agent(response: str) -> Agent:
    agent = Agent(
        AgentConfig(name="conv", llm_config=_llm()),
        GraphSchema(state_schema=_State),
        GraphCompileOptions(checkpointer=InMemorySaver()),
    )
    node = _ReplyNode("reply", response)
    agent.add_node(node)
    agent.add_edge(START_NODE, node.name)
    agent.add_edge(node.name, END_NODE)
    agent.compile()
    return agent


def _messages(agent: Agent, session_id: str):
    return agent._get_agent_state(session_id).conversation.messages


def test_completed_turn_appends_user_and_assistant():
    agent = _agent("hello")
    sid = "s1"
    agent.invoke(sid, UserInput(text="hi"))
    msgs = _messages(agent, sid)
    assert len(msgs) == 2
    assert msgs[0].role == Role.USER and msgs[0].content == "hi"
    assert msgs[1].role == Role.ASSISTANT and msgs[1].content == "hello"

    agent.invoke(sid, UserInput(text="again"))
    msgs = _messages(agent, sid)
    assert len(msgs) == 4
    assert msgs[2].content == "again"
    assert msgs[3].content == "hello"


def test_empty_response_still_appends_placeholder():
    agent = _agent("")
    sid = "s1"
    result = agent.invoke(sid, UserInput(text="q"))
    msgs = _messages(agent, sid)
    assert len(msgs) == 2
    assert msgs[0].content == "q"
    assert msgs[1].content == "本轮已结束，无最终回复。"
    assert result.text == ""


def test_restore_without_checkpoint_keeps_conversation():
    agent = _agent("kept")
    sid = "s1"
    agent.invoke(sid, UserInput(text="first"))
    assert len(_messages(agent, sid)) == 2
    usage_before = agent._get_agent_state(sid).token_usage.total_tokens

    agent.restore_checkpoint(sid, None)
    msgs = _messages(agent, sid)
    assert len(msgs) == 2
    assert msgs[1].content == "kept"
    assert agent._get_agent_state(sid).token_usage.total_tokens == usage_before


def test_restore_to_baseline_clears_turn_only():
    agent = _agent("ok")
    sid = "s1"
    agent.invoke(sid, UserInput(text="a"))
    snap = agent.get_state(sid)
    checkpoint_id = (snap.config or {}).get("configurable", {}).get("checkpoint_id")
    assert checkpoint_id

    agent._get_session(sid).start_turn(UserInput(text="in-flight"))
    agent.restore_checkpoint(sid, str(checkpoint_id))
    assert agent._get_session(sid).current_turn is None
    assert len(_messages(agent, sid)) == 2
