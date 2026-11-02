from langgraph.runtime import Runtime

from ....common import get_logger
from ....utils import MessageAdapter
from ...graph import BaseContext, BaseState, Node, SubGraph, START_NODE, END_NODE, GraphSchema
from ...llm import LLMConfig
from ...model.input import UserInput
from ...runtime.human_in_the_loop import HITLSubgraph
from ...tool import ToolExecutor, ToolNode, ToolRegistry
from ..strategy import BaseStrategy
from ..strategy_task import StrategyTask
from .node import ActionNode, FinalNode, ReasonNode
from .schema import ReActContext, ReActInput, ReActOutput, ReActState


logger = get_logger("react")


class ReActStrategy(BaseStrategy):
    """
    ReAct 策略
    """
    def __init__(self, llm_config: LLMConfig, tool_registry: ToolRegistry):
        super().__init__(state_schema=ReActState, input_schema=ReActInput, output_schema=ReActOutput, context_schema=ReActContext)
        self._llm_config = llm_config
        self._tool_registry = tool_registry
        self._tool_executor = ToolExecutor(self._tool_registry)

    def build(self) -> SubGraph:
        """
        Build the ReAct strategy SubGraph
        """
        graph = SubGraph(
            name="ReAct",
            graph_schema=GraphSchema(
                state_schema=ReActState,
                input_schema=ReActInput, 
                output_schema=ReActOutput, 
                context_schema=ReActContext
            ),
        )

        # 定义节点
        reason_node = ReasonNode(name="reason", llm_config=self._llm_config)
        action_node = ActionNode(name="action", llm_config=self._llm_config)
        tool_node = ToolNode(name="tool", tool_executor=self._tool_executor, message_field="trajectory")
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
        # 构建Task
        if isinstance(state.input, UserInput):
            text = state.input.text
            attachments = list(state.input.attachments)
            user_content = MessageAdapter.to_human_message(state.input).content
        else:
            text = str(state.input or "")
            attachments = []
            user_content = text
        task = StrategyTask(
            name="react",
            description=text,
            goal=text,
            attachments=attachments,
        )
        logger.info("to_strategy_input | task=%s, user_content=%s", task, user_content)
        logger.info("to_strategy_input | task=%s, messages=%s", task, len(state.context.messages))

        return ReActInput(
            task=task,
            steps=[step.model_copy(deep=True) for step in state.steps],
            current_step=(state.current_step.model_copy(deep=True) if state.current_step is not None else None),
            context=state.context.model_copy(deep=True)
        )

    def to_strategy_context(self, context: BaseContext | None = None) -> ReActContext | None:
        """
        将 Parent Context 映射为 Strategy Context

        active_skills 必须与 Parent 保持同一 dict 引用，否则 HITL resume 后
        load_skill 写回会丢失。
        """
        if context is None:
            raise ValueError("BaseContext is required for ReAct strategy")
        
        active_skills = context.active_skills
        react_context = ReActContext(
            session_state=context.session_state,
            resources=context.resources,
            active_skills=active_skills,
            agent_result=context.agent_result,
        )

        if react_context.session_state is not context.session_state:
            object.__setattr__(react_context, "session_state", context.session_state)
        if react_context.active_skills is not active_skills:
            object.__setattr__(react_context, "active_skills", active_skills)

        return react_context

    def to_parent_state(self, output: ReActOutput) -> dict:
        """将 Strategy Output 映射为 Parent State 更新内容"""
        # 获取当前上下文
        context = output.context.model_copy(deep=True)
        return {
            "steps": [step.model_copy(deep=True) for step in output.steps],
            "current_step": (output.current_step.model_copy(deep=True) if output.current_step is not None else None),
            "response": output.response,
            "context": context,
        }


class ReActNode(Node):
    """
    ReActStrategy Node: ReAct策略子图节点
    """
    def __init__(self, name: str, strategy: ReActStrategy):
        super().__init__(name)
        self._strategy = strategy

    def run(self, state: BaseState, runtime: Runtime[BaseContext]) -> dict:
        result = self._strategy.invoke(state, runtime.context)
        return result

    async def arun(self, state: BaseState, runtime: Runtime[BaseContext], config=None) -> dict:
        return await self._strategy.ainvoke(state, runtime.context)
