from pydantic import BaseModel

from .schema import BaseContext, BaseInput, BaseOutput, BaseState


class GraphSchema(BaseModel):
    """
    Agent Graph Schema 配置
    """
    state_schema: type[BaseState]
    context_schema: type[BaseContext] | None = None
    input_schema: type[BaseInput] | None = None
    output_schema: type[BaseOutput] | None = None
