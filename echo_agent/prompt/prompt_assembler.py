from ..core.model.skill import SkillStatus, SkillRuntimeContext
from .loader import PromptLoader


class PromptAssembler:
    """
    提示词组装器
    """
    @staticmethod
    def assemble(
        agent_prompt: str | None = None,
        system_prompt: str | None = None,
        active_skills: dict[str, SkillRuntimeContext] | None = None,
    ) -> str:
        prompts: list[str] = []

        # Agent System Prompt
        if agent_prompt:
            prompts.append(agent_prompt.strip())

        # Tool Policy
        tool_policy = PromptLoader.load("prompt/tool_call_policy.md")
        if tool_policy:
            prompts.append(tool_policy)

        # Skill Usage Policy
        skill_policy = PromptLoader.load("prompt/skill_usage_policy.md")
        if skill_policy:
            prompts.append(skill_policy)

        # System Prompt（节点 / 策略提示词）
        if system_prompt:
            prompts.append(system_prompt)

        # Loaded Skills（来自 Runtime Context，不进历史）
        skill_prompt = PromptAssembler._build_skill_prompt(active_skills)
        if skill_prompt:
            prompts.append(skill_prompt)

        return "\n\n".join(prompts)

    @staticmethod
    def _build_skill_prompt(active_skills: dict[str, SkillRuntimeContext] | None = None) -> str:
        if not active_skills:
            return ""

        prompts: list[str] = [
            "# Loaded Skills"
        ]

        for skill_name, skill_context in active_skills.items():
            if skill_context.status != SkillStatus.LOADED:
                continue
            if not skill_context.instruction:
                continue
            prompts.append(
                f"## Skill: {skill_name}\n\n{skill_context.instruction.strip()}"
            )

        return "\n\n".join(prompts)
