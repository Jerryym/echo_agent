from functools import cached_property
import uuid

from langchain_core.runnables import RunnableConfig

from ...graph import BaseContext, BaseState, Node, SubGraph, START_NODE, END_NODE
from .node import ApprovalFlow, InputFlow, NormalizeResultNode
from .schema import HITLInput, HITLOutput, HITLState, HITLType

class HITLSubgraph:
    """
    HITL 动态子图：一张图内按 type 分支，仅通过 as_node / invoke 接入父图。
    """
    def __init__(self):
        self.state_schema = HITLState
        self.input_schema = HITLInput
        self.output_schema = HITLOutput
        self.context_schema = None

    @cached_property
    def compiled_graph(self):
        """
        编译后的 HITL 子图（缓存一次）
        """
        return self.build().as_callable()

    def build(self) -> SubGraph:
        """
        构建 HITL 子图：START --type--> input|approval --> normalize --> END
        """
        graph = SubGraph(
            name="HITL",
            state_schema=self.state_schema,
            context_schema=self.context_schema,
            input_schema=self.input_schema,
            output_schema=self.output_schema,
        )

        input_flow = InputFlow(name="input_flow")
        approval_flow = ApprovalFlow(name="approval_flow")
        normalize = NormalizeResultNode(name="normalize_result")

        graph.add_node(input_flow)
        graph.add_node(approval_flow)
        graph.add_node(normalize)

        graph.add_conditional_edges(
            START_NODE,
            self._type_router,
            {
                "input_flow": input_flow.name,
                "approval_flow": approval_flow.name,
            },
        )
        graph.add_edge(input_flow.name, normalize.name)
        graph.add_edge(approval_flow.name, normalize.name)
        graph.add_edge(normalize.name, END_NODE)

        return graph

    def as_node(self) -> Node:
        """
        作为节点加入父图（Call a subgraph inside a node）
        """
        return HITLNode(name="HITL", hitl=self, input_builder=self.to_hitl_input)

    def to_hitl_state(self, input: HITLInput) -> HITLState:
        """
        将 Parent State 映射为 HITL Input
        """
        return HITLState(
            id=str(uuid.uuid4()),
            type=input.type,
            description=input.description,
            payload=input.payload,
            status="pending",
        )

    def to_parent_state(self, output: HITLOutput) -> dict:
        """
        将 HITL Output 映射为 Parent State 更新内容
        """
        return {
            "hitl_result": output.model_dump(),
        }

    def invoke(self, input: HITLInput, context: BaseContext | None = None, config: RunnableConfig | None = None) -> dict:
        """
        调用 HITL 子图
        """
        state = self.to_hitl_state(input)
        output = self.compiled_graph.invoke(state, context=context, config=config)
        if self.output_schema is not None and isinstance(output, dict):
            output = self.output_schema(**output)
        return self.to_parent_state(output)

    def _type_router(self, state: HITLState) -> str:
        """
        按 HITLType 路由到对应 flow
        """
        if state.type == HITLType.INPUT:
            print("[HITLSubgraph] routing to input_flow")
            return "input_flow"
        if state.type == HITLType.APPROVAL:
            print("[HITLSubgraph] routing to approval_flow")
            return "approval_flow"
        raise ValueError(f"unsupported HITL type: {state.type}")


class HITLNode(Node):
    """
    HITLSubgraph Node：在父节点内调用 HITL 动态子图
    """
    def __init__(self, name: str, hitl: HITLSubgraph, input: HITLInput):
        super().__init__(name)
        self._hitl = hitl
        self._input = input

    def run(self, state: BaseState, context: BaseContext | None = None, config=None) -> dict:
        return self._hitl.invoke(self._input, context, config)
