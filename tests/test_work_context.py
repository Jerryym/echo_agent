"""工作上下文唯一来源、正式记录隔离及 Checkpoint 回归。无需模型服务。"""
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt

from echo_agent import Agent, AgentConfig, BaseContext, BaseState, LLMConfig, Node, UserInput
from echo_agent.core.graph import BaseInput, BaseOutput, GraphCompileOptions, GraphSchema
from echo_agent.core.model.agent import AgentResult
from echo_agent.core.model.context import ContextState
from echo_agent.core.model.message import Message, Role
from echo_agent.core.model.session import SessionState
from echo_agent.core.model.tool import ToolCall, ToolResult, ToolState
from echo_agent.core.strategy.react.node.action_node import ActionNode
from echo_agent.core.strategy.react.node.final_node import FinalNode
from echo_agent.core.strategy.react.react_strategy import ReActStrategy
from echo_agent.core.strategy.react.schema import ReActContext, ReActOutput, ReActState, build_react_history
from echo_agent.core.tool import ToolNode


def llm_config() -> LLMConfig:
    return LLMConfig(base_url="http://localhost/v1", api_key="offline", model_name="mock")


class _CompactReply(Node):
    def run(self, state: BaseState, runtime: Runtime[BaseContext]) -> dict[str, object]:
        del runtime
        context = state.context.model_copy(deep=True)
        context.messages = [
            Message(role=Role.SYSTEM, content="[Compacted Context]\nsummary"),
            context.messages[-1],
            Message(role=Role.ASSISTANT, content="reply"),
        ]
        return {"context": context, "response": "reply"}

    async def arun(self, state: BaseState, runtime: Runtime[BaseContext]) -> dict[str, object]:
        return self.run(state, runtime)


class WorkContextTests(unittest.TestCase):
    def test_graph_schema_and_history_have_one_source(self) -> None:
        for schema in (BaseInput, BaseOutput, BaseState):
            self.assertNotIn("conversation", schema.model_fields)
        context = ContextState(messages=[Message(role=Role.USER, content="hello")])
        history = build_react_history(context)
        history[0].content = "changed"
        self.assertEqual(context.messages[0].content, "hello")

    def test_subgraph_does_not_reinstall_removed_trajectory(self) -> None:
        strategy = ReActStrategy(llm_config(), Mock())
        parent = BaseState(input="task", context=ContextState(messages=[Message(role=Role.USER, content="task")]))
        child = strategy.to_strategy_input(parent)
        child.context.messages.append(Message(role=Role.ASSISTANT, content="child"))
        self.assertEqual(len(parent.context.messages), 1)
        output = ReActOutput(
            response="reply",
            context=ContextState(messages=[Message(role=Role.SYSTEM, content="summary")]),
            trajectory=[Message(role=Role.ASSISTANT, content="removed old text")],
        )
        update = strategy.to_parent_state(output)
        self.assertNotIn("conversation", update)
        self.assertEqual([m.content for m in update["context"].messages], ["summary"])

    def test_tool_call_and_results_enter_context_once(self) -> None:
        context = ReActContext(session_state=SessionState(), agent_result=AgentResult())
        runtime = Runtime(context=context)
        call = ToolCall(name="echo", tool_call_id="call-1", args={})
        for asynchronous in (False, True):
            state = ReActState(context=ContextState(messages=[Message(role=Role.USER, content="task")]))
            action = ActionNode("action", llm_config())
            with patch.object(action, "_get_step_increment", return_value=1):
                update = action._handle_ready([call], state, context, Mock()).update
            state = state.model_copy(update=update)
            self.assertEqual(len(state.context.messages), 2)
            result = ToolResult(name="echo", tool_call_id="call-1", success=True, result="result")
            executor = Mock()
            executor.execute.return_value = result
            executor.aexecute = AsyncMock(return_value=result)
            tool = ToolNode("tool", executor, message_field="trajectory")
            update = asyncio.run(tool.arun(state, runtime)) if asynchronous else tool.run(state, runtime)
            work = update["context"]
            self.assertEqual([m.role for m in work.messages], [Role.USER, Role.ASSISTANT, Role.TOOL])
            self.assertEqual(work.messages[1].tool_calls[0].tool_call_id, work.messages[2].tool_call_id)
            self.assertEqual(len(build_react_history(work)), 3)
            self.assertEqual(len(state.context.messages), 2)
            self.assertEqual(len(context.session_state.items), 1)
            final_context = FinalNode._context_with_response(state.model_copy(update={"context": work}), "reply")
            self.assertEqual(len(final_context.messages), 4)

    def test_context_commit_preserves_formal_history_across_turns(self) -> None:
        for asynchronous in (False, True):
            agent = Agent(AgentConfig(name="test", llm_config=llm_config(), context_window=90_000), GraphSchema(state_schema=BaseState), GraphCompileOptions(checkpointer=InMemorySaver()))
            agent.add_node(_CompactReply("reply"))
            agent.add_edge(START, "reply")
            agent.add_edge("reply", END)
            agent.compile()
            for text in ("first", "second"):
                if asynchronous:
                    asyncio.run(agent.ainvoke("s", UserInput(text=text)))
                else:
                    agent.invoke("s", UserInput(text=text))
            state = agent.get_sesion("s").state
            self.assertEqual([m.content for m in state.conversation.messages], ["first", "reply", "second", "reply"])
            self.assertEqual([m.content for m in state.context.messages], ["[Compacted Context]\nsummary", "second", "reply"])
            self.assertEqual(state.context.context_window, 90_000)
            self.assertNotIn("conversation", agent.get_state("s").values)

    def test_interrupt_resume_keeps_work_context(self) -> None:
        graph = StateGraph(BaseState)
        def prepare(state: BaseState) -> dict[str, object]:
            context = state.context.model_copy(deep=True)
            context.messages.append(Message(role=Role.ASSISTANT, content="prepared"))
            return {"context": context}
        def wait(state: BaseState) -> dict[str, object]:
            answer = interrupt("approval")
            context = state.context.model_copy(deep=True)
            context.messages.append(Message(role=Role.ASSISTANT, content=str(answer)))
            return {"context": context}
        graph.add_node("prepare", prepare)
        graph.add_node("wait", wait)
        graph.add_edge(START, "prepare")
        graph.add_edge("prepare", "wait")
        graph.add_edge("wait", END)
        compiled = graph.compile(checkpointer=InMemorySaver())
        config = {"configurable": {"thread_id": "resume"}}
        compiled.invoke(BaseState(context=ContextState(messages=[Message(role=Role.USER, content="task")])), config)
        self.assertTrue(compiled.get_state(config).next)
        output = compiled.invoke(Command(resume="approved"), config)
        self.assertEqual([m.content for m in output["context"].messages], ["task", "prepared", "approved"])


if __name__ == "__main__":
    unittest.main()
