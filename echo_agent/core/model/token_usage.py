from pydantic import BaseModel, Field


class TokenUsage(BaseModel):
    """
    词元使用情况

    参数：
        input_tokens: 输入的token数量
        output_tokens: 输出的token数量
        cache_creation: 创建缓存的token数量
        cache_hit: 缓存命中的token数量
        reasoning_tokens: 推理token数量
    """
    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)
    cache_creation: int = Field(default=0)
    cache_hit: int = Field(default=0)
    reasoning_tokens: int = Field(default=0)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def add(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_creation=self.cache_creation + other.cache_creation,
            cache_hit=self.cache_hit + other.cache_hit,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
        )
