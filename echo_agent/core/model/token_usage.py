from pydantic import BaseModel, Field


class TokenUsage(BaseModel):
    """
    词元使用情况

    参数：
        input_tokens: 输入的token数量
        output_tokens: 输出的token数量
    """
    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def add(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
        )
