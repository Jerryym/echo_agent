from typing import Literal
from pydantic import BaseModel, Field

from .....prompt import PromptLoader
from ....graph import Node
from ....llm import LLMClient, LLMConfig
from ..schema import ReActContext, ReActState


class ReasonResult(BaseModel):
    """
    Reason Result
    """
    reasoning: str = Field(
        description="Reasoning about the current task state."
    )
    information_status: Literal["sufficient", "insufficient"] = Field(
        description="Whether the currently available information is sufficient to generate the final response."
        )


class ReasonNode(Node):
    """
    Reason Node：推理节点
    """
    def __init__(self, name: str, llm_config: LLMConfig):
        super().__init__(name)
        self._llm_client = LLMClient(llm_config)
        self._prompt = PromptLoader.load("core/strategy/react/prompt/reasoning.md")

    def run(self, state: ReActState, context: ReActContext | None = None) -> dict:
        """
        Run the node
        """
        # print(
        #     f"[ReAct][reason] enter | step={state.step_count} retry={state.retry_count} "
        #     f"finished={state.is_finished}"
        # )

        # 检查工具执行失败
        if self._has_tool_error(state):
            failed = [r.name for r in state.tool_results if not r.success]
            # print(f"[ReAct][reason] tool error detected: {failed}")
            result = {
                "retry_count": state.retry_count + 1,
            }
            if context and state.retry_count + 1 >= context.retry_max_count:
                result["is_finished"] = True
            # print(f"[ReAct][reason] skip LLM, return {result}")
            return result

        # 构建输入
        input = self._build_input(state)
        # print(
        #     f"[ReAct][reason] llm_input keys={list(input.keys())} "
        #     f"observations={input.get('observations', [])}"
        # )
        # 调用llm
        response = self._llm_client.invoke_structured(
            schema=ReasonResult, 
            prompt=self._prompt, 
            user_input=input, 
            history=state.messages,
            method="json_schema",
        )
        # 更新状态
        result = {
            "reasoning": response.reasoning,
            "information_status": response.information_status,
        }
        # print("[ReAct][reason] " f"status={response.information_status} "f"reasoning={response.reasoning}")
        return result

    def _build_input(self, state: ReActState) -> dict:
        """
        构建输入
        """
        return {
            "input": state.input,
            "messages": state.messages,
            "observations": state.observations + self._build_observations(state),
        }

    def _build_observations(self, state: ReActState) -> list[str]:
        """
        构建观察结果
        """
        return [
            tool_result.result
            for tool_result in state.tool_results
        ]

    def _has_tool_error(self, state: ReActState) -> bool:
        """
        判断是否存在工具错误
        """
        return any(not result.success for result in state.tool_results)
