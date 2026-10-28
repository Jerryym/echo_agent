from langgraph.runtime import Runtime

from .....common import get_logger
from .....prompt import PromptAssembler, PromptLoader
from .....utils import update_agent_result
from ....graph import Node
from ....llm import LLMClient, LLMConfig
from ....model.agent import AgentMode
from ....model.step import Step
from ....model.context import ContextState
from ....model.message import Message, Role, append_messages
from ....runtime.runtime_config import RuntimeConfig
from ....runtime.context import ContextCompactor
from ..schema import ReActContext, ReActState, build_react_history

logger = get_logger("react.final")


class FinalNode(Node):
    """
    Final Node：最终节点
    """
    def __init__(self, name: str, llm_config: LLMConfig):
        super().__init__(name)
        self._llm_client = LLMClient(llm_config)
        self._prompt = PromptLoader.load("core/strategy/react/prompt/final.md")
        self._context_compactor = ContextCompactor(llm_config) # 上下文压缩器

    def run(self, state: ReActState, runtime: Runtime[ReActContext]) -> dict:
        """
        Run the node
        """
        logger.info("enter | step=%s retry=%s", state.step_count, state.retry_count)
        logger.info("observations=%s", [observation.model_dump_json() for observation in state.observations])

        # 判断是否需要压缩上下文
        if self._context_compactor.should_compact(state.context):
            compacted_context, token_usage = self._context_compactor.compress(state.context)
            logger.info("context compacted | tokens=%s", token_usage.total_tokens)
            state.context = compacted_context
            update_agent_result(runtime.context, '上下文已压缩', token_usage) 
            
        # 获取运行时信息
        runtime_config = RuntimeConfig.get_runtime_config()
        # 构建输入
        input = self._build_input(state)
        # 构建历史记录
        history = self._build_history(state, runtime.context)

        # 调用llm
        step = Step()
        state.steps = [*state.steps, step]
        state.current_step = step
        try:
            response = self._llm_client.invoke(
                prompt=self._build_prompt(runtime.context, runtime_config.agent_mode),
                user_input=input,
                history=history,
                config=runtime_config.to_llm_runnable_config(),
            )
            step.token_usage = response.token_usage.model_copy(deep=True)
        except Exception as exc:
            step.error = str(exc)
            state.current_step = None
            logger.warning("final step failed: %s", exc)
            text = "本次回复生成失败，请稍后重试。"
            return {
                "steps": state.steps,
                "current_step": None,
                "task_status": "failed",
                "response": text,
                "context": self._context_with_response(state, text),
                "trajectory": [Message(role=Role.ASSISTANT, content=text)],
            }
        finally:
            state.current_step = None
        
        update_agent_result(runtime.context, response.text, response.token_usage)
        return {
            "steps": state.steps,
            "current_step": state.current_step,
            "response": response.text,
            "context": self._context_with_response(state, response.text),
            "trajectory": [Message(role=Role.ASSISTANT, content=response.text)],
        }

    async def arun(self, state: ReActState, runtime: Runtime[ReActContext]) -> dict:
        """
        异步运行
        """
        logger.info("enter | step=%s retry=%s", state.step_count, state.retry_count)
        logger.info("observations=%s", [observation.model_dump_json() for observation in state.observations])

        # 判断是否需要压缩上下文
        if self._context_compactor.should_compact(state.context):
            compacted_context, token_usage = await self._context_compactor.acompress(state.context)
            logger.info("context compacted | tokens=%s", token_usage.total_tokens)
            state.context = compacted_context
            update_agent_result(runtime.context, '上下文已压缩', token_usage) 

        # 获取运行时信息
        runtime_config = RuntimeConfig.get_runtime_config()
        # 构建输入
        input = self._build_input(state)
        # 构建历史记录
        history = self._build_history(state, runtime.context)

        # 调用llm
        step = Step()
        state.steps = [*state.steps, step]
        state.current_step = step
        try:
            response = await self._llm_client.ainvoke(
                prompt=self._build_prompt(runtime.context, runtime_config.agent_mode),
                user_input=input,
                history=history,
                config=runtime_config.to_llm_runnable_config(),
            )
            step.token_usage = response.token_usage.model_copy(deep=True)
        except Exception as exc:
            step.error = str(exc)
            state.current_step = None
            logger.warning("final step failed: %s", exc)
            text = "本次回复生成失败，请稍后重试。"
            return {
                "steps": state.steps,
                "current_step": None,
                "task_status": "failed",
                "response": text,
                "context": self._context_with_response(state, text),
                "trajectory": [Message(role=Role.ASSISTANT, content=text)],
            }
        finally:
            state.current_step = None
        
        update_agent_result(runtime.context, response.text, response.token_usage)
        return {
            "steps": state.steps,
            "current_step": state.current_step,
            "response": response.text,
            "context": self._context_with_response(state, response.text),
            "trajectory": [Message(role=Role.ASSISTANT, content=response.text)],
        }

# region Private Functions
    @staticmethod
    def _context_with_response(state: ReActState, text: str) -> ContextState:
        context = state.context.model_copy(deep=True)
        context.messages = append_messages(
            context.messages,
            [Message(role=Role.ASSISTANT, content=text)],
        )
        return context

    def _build_prompt(self, context: ReActContext, agent_mode: AgentMode) -> str:
        """构建系统提示词"""
        resources = context.resources
        return PromptAssembler.assemble(
            agent_prompt=resources.system_prompt if resources else None,
            system_prompt=self._prompt,
            agent_mode=agent_mode,
            skill_frontmatter_list=resources.skill_frontmatter_list if resources else None,
            active_skills=context.active_skills,
        )

    def _build_input(self, state: ReActState) -> dict:
        """构建输入"""
        return {
            "task": state.task.dump_attachments(),
            "assessment": state.assessment,
            "task_status": state.task_status,
            # "observations": state.observations,
        }
    
    def _build_history(self, state: ReActState, context: ReActContext | None = None) -> list[Message]:
        """构建跨轮会话历史与本轮执行轨迹"""
        if context is None:
            raise ValueError("ReActContext is required for FinalNode")
        return build_react_history(state.context)
# endregion
