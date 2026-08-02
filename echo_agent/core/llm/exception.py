from typing import Optional


class LLMException(Exception):
    """
    LLM 模块基础异常
    """
    def __init__(self, message: str, detail: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.detail = detail

    def __str__(self):
        if self.detail:
            return f"{self.message} | detail={self.detail}"
        return self.message


class LLMInitializeError(LLMException):
    """
    模型初始化异常

    场景：
    - provider 不支持
    - api_key/base_url 配置错误
    - model_name 无效
    """
    pass


class LLMInvokeError(LLMException):
    """
    模型调用异常

    场景：
    - 网络错误
    - 超时
    - LangChain invoke 失败
    - 模型返回非法结果
    """
    pass


class LLMResponseDecodeError(LLMException):
    """
    响应解析异常

    场景：
    - response 结构不符合预期
    - content 缺失
    - message 类型不支持
    """
    pass