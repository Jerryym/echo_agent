from ...graph import Node, SubGraph, START_NODE, END_NODE
from ...llm import LLMConfig
from ...tool import ToolExecutor, ToolNode
from ..strategy import BaseStrategy
from .node import ActionNode, FinalNode, ReasonNode
from .react_node import ReActNode
from .schema import ReActContext, ReActInput, ReActOutput, ReActState


class ReActStrategy(BaseStrategy):
    """
    ReAct 策略
    """
    def __init__(self, llm_config: LLMConfig, tool_executor: ToolExecutor):
        super().__init__(state_schema=ReActState, input_schema=ReActInput, output_schema=ReActOutput, context_schema=ReActContext)
        self._llm_config = llm_config
        self._tool_executor = tool_executor

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
        action_node = ActionNode(name="action", llm_config=self._llm_config)
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
        As a node in the parent graph
        """
        return ReActNode(name="ReAct", subgraph=self.build())

    def _reason_router(self, state: ReActState) -> str:
        """
        Reason 节点路由

        返回:
            action: 动作节点
            final: 最终节点
        """
        if state.is_finished:
            return "final"

        return "action"


    def _action_router(self, state: ReActState) -> str:
        """
        Action 节点路由

        返回:
            tool: 工具节点
            reason: 推理节点
            final: 最终节点
        """
        if state.tool_calls:
            return "tool"

        if state.is_finished:
            return "final"

        return "reason"
