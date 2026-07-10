from langchain_core.messages import AIMessage

from ...graph import BaseContext, BaseState, Node, START_NODE, END_NODE, SubGraph
from ...llm import LLMConfig
from ...tool import ToolExecutor, ToolNode, ToolRegistry
from ..strategy import BaseStrategy
from .node import ActionNode, FinalNode, ReasonNode
from .schema import ReActContext, ReActInput, ReActOutput, ReActState


class ReActStrategy(BaseStrategy):
    """
    ReAct 策略
    """
    def __init__(self, llm_config: LLMConfig, tool_registry: ToolRegistry):
        super().__init__(state_schema=ReActState, input_schema=ReActInput, output_schema=ReActOutput, context_schema=ReActContext)
        self._llm_config = llm_config
        self._tool_registry = tool_registry
        self._tool_executor = ToolExecutor(self._tool_registry)
        self._max_steps = 10
        self._retry_max_count = 3

    def build(self) -> SubGraph:
        """
        Build the ReAct strategy SubGraph
        """
        graph = SubGraph(
            name="ReAct",
            state_schema=self.state_schema,
            context_schema=self.context_schema,
            input_schema=self.input_schema,
            output_schema=self.output_schema,
        )

        reason_node = ReasonNode(name="reason", llm_config=self._llm_config)
        action_node = ActionNode(name="action", llm_config=self._llm_config, tool_list=self._tool_registry.get_tools())
        tool_node = ToolNode(name="tool", tool_executor=self._tool_executor)
        final_node = FinalNode(name="final", llm_config=self._llm_config)

        graph.add_node(reason_node)
        graph.add_node(action_node)
        graph.add_node(tool_node)
        graph.add_node(final_node)

        # START -> reason
        graph.add_edge(START_NODE, reason_node.name)
        # reason -> action
        graph.add_conditional_edges(reason_node.name, self._reason_router)
        # action -> tool/reason/final
        graph.add_conditional_edges(action_node.name, self._action_router)
        # tool -> reason
        graph.add_edge(tool_node.name, reason_node.name)
        # final -> END
        graph.add_edge(final_node.name, END_NODE)

        return graph

    def as_node(self) -> Node:
        """
        作为节点加入父图（Call a subgraph inside a node）
        """
        return ReActNode(name="ReAct", strategy=self)

    def to_strategy_input(self, state: BaseState, context: BaseContext | None = None) -> ReActInput:
        """
        将 Parent State 映射为 Strategy Input
        """
        return ReActInput(
            input=state.input,
            messages=state.messages
        )

    def to_strategy_context(self, context: BaseContext | None = None) -> ReActContext | None:
        """
        将 Parent Context 映射为 Strategy Context
        """
        return ReActContext()

    def to_parent_state(self, output: ReActOutput) -> dict:
        """
        将 Strategy Output 映射为 Parent State 更新内容
        """
        return {
            "response": output.response,
            "messages": output.messages or [AIMessage(content=output.response)],
        }

    def invoke(self, state: BaseState, context: BaseContext | None = None) -> dict:
        input = self.to_strategy_input(state, context)
        strategy_context = self.to_strategy_context(context)
        # print(f"[ReAct][invoke] strategy_input={input.model_dump()}")

        output = self.compiled_graph.invoke(input, context=strategy_context)
        # print(f"[ReAct][invoke] raw_output={output}")

        if self.output_schema is not None and isinstance(output, dict):
            output = self.output_schema(**output)

        parent_state = self.to_parent_state(output)
        # print(f"[ReAct][invoke] parent_state={parent_state}")
        return parent_state

    def _reason_router(self, state: ReActState) -> str:
        """
        Reason 节点路由

        返回:
            action: 动作节点
            final: 最终节点
        """
        if state.information_status == "sufficient":
            target = "final"
            reason = "information_status=sufficient"

        elif state.step_count >= self._max_steps:
            target = "final"
            reason = f"step_count={state.step_count} >= max={self._max_steps}"

        elif state.retry_count >= self._retry_max_count:
            target = "final"
            reason = f"retry_count={state.retry_count} >= max={self._retry_max_count}"

        else:
            target = "action"
            reason = "information_status=insufficient"

        print(f"[ReAct][route] reason -> {target} ({reason})")
        return target

    def _action_router(self, state: ReActState) -> str:
        """
        Action 节点路由

        返回:
            tool: 工具节点
            final: 最终节点
        """
        if state.is_finished:
            target = "final"
            reason = "is_finished=True"
        elif state.tool_calls:
            target = "tool"
            names = [tc.name for tc in state.tool_calls]
            reason = f"tool_calls={names}"
        else:
            target = "final"
            reason = "no tool_calls"

        print(f"[ReAct][route] action -> {target} ({reason})")
        return target


class ReActNode(Node):
    """
    ReActStrategy Node: ReAct策略子图节点
    """
    def __init__(self, name: str, strategy: ReActStrategy):
        super().__init__(name)
        self._strategy = strategy

    def run(self, state: BaseState, context: BaseContext | None = None) -> dict:
        # user_text = getattr(state.input, "text", state.input)
        # print(f"\n[ReAct] ===== 开始 ===== input={user_text!r}")
        result = self._strategy.invoke(state, context)
        # print(f"[ReAct] ===== 结束 ===== response={result.get('response', '')!r}\n")
        return result
