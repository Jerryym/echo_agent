from langchain_core.messages import AIMessage

from ...graph import BaseContext, BaseState, Node, START_NODE, END_NODE, SubGraph
from ...llm import LLMConfig
from ...tool import ToolExecutor, ToolNode, ToolRegistry
from ..strategy import BaseStrategy
from .node import ActionNode, FinalNode, ReasonNode
from .schema import ReActContext, ReActInput, ReActOutput, ReActState
from ...runtime.human_in_the_loop import HITLSubgraph


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
        action_node = ActionNode(
            name="action",
            llm_config=self._llm_config,
            tool_list=self._tool_registry.list_definitions(),
        )
        tool_node = ToolNode(name="tool", tool_executor=self._tool_executor)
        final_node = FinalNode(name="final", llm_config=self._llm_config)
        hitl_node = HITLSubgraph().as_node()

        graph.add_node(reason_node)
        graph.add_node(action_node)
        graph.add_node(tool_node)
        graph.add_node(final_node)
        graph.add_node(hitl_node)

        # START -> reason
        graph.add_edge(START_NODE, reason_node.name)
        # HITL -> action
        graph.add_edge(hitl_node.name, action_node.name)
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
        return ReActContext(
            max_steps=self._max_steps,
            retry_max_count=self._retry_max_count,
        )

    def to_parent_state(self, output: ReActOutput) -> dict:
        """
        将 Strategy Output 映射为 Parent State 更新内容
        """
        return {
            "response": output.response,
            "messages": output.messages or [AIMessage(content=output.response)],
        }


class ReActNode(Node):
    """
    ReActStrategy Node: ReAct策略子图节点
    """
    def __init__(self, name: str, strategy: ReActStrategy):
        super().__init__(name, is_async=True)
        self._strategy = strategy

    def run(self, state: BaseState, context: BaseContext | None = None) -> dict:
        # user_text = getattr(state.input, "text", state.input)
        # print(f"\n[ReAct] ===== 开始 ===== input={user_text!r}")
        result = self._strategy.invoke(state, context)
        # print(f"[ReAct] ===== 结束 ===== response={result.get('response', '')!r}\n")
        return result

    async def arun(self, state: BaseState, context: BaseContext | None = None, config=None) -> dict:
        return await self._strategy.ainvoke(state, context)
