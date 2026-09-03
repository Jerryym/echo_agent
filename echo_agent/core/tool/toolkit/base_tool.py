# 基础工具

from dataclasses import is_dataclass
from typing import Any, TypeAlias, cast, is_typeddict

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, TypeAdapter

 
JsonValue: TypeAlias = (None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"])
JsonObject: TypeAlias = dict[str, JsonValue]
StructuredOutputSchema: TypeAlias = type[Any] | JsonObject


def create_structured_output_tool(schema: StructuredOutputSchema) -> BaseTool:
    """创建结构化输出工具"""
    json_schema = _build_json_schema(schema)
    @tool(args_schema=json_schema, infer_schema=False)
    def structured_output_tool(**kwargs: Any) -> JsonObject:
        """
        Submit the final structured output.

        Use this tool when the task is complete and return all required fields.

        Returns:
            Structured output as a JSON object.
        """
        return _validate_structured_output(schema, kwargs)

    return structured_output_tool

def _build_json_schema(schema: StructuredOutputSchema) -> dict[str, Any]:
    """将结构化输出Schema转换成JSON Schema"""
    if isinstance(schema, dict): # 字典
        json_schema = cast(dict[str, Any], schema.copy())
    elif _is_pydantic_model(schema):  # pydantic模型
        json_schema = schema.model_json_schema()
    elif is_dataclass(schema) or is_typeddict(schema):  # dataclass 或 TypedDict
        adapter = TypeAdapter(schema)
        json_schema = adapter.json_schema()
    else:
        raise TypeError(
            "Unsupported structured output schema: "
            f"{schema!r}. Expected a Pydantic model, dataclass, "
            "TypedDict, or JSON Schema."
        )

    if json_schema.get("type") != "object":
        raise ValueError("Structured output schema must describe a JSON object.")
    return json_schema

def _validate_structured_output(schema: StructuredOutputSchema, value: dict[str, Any]) -> JsonObject:
    """验证结构化输出"""
    if isinstance(schema, dict):
        return _to_json_object(value)

    adapter = TypeAdapter(schema)
    validated = adapter.validate_python(value)
    json_value = adapter.dump_python(
        validated,
        mode="json",
    )

    return _to_json_object(json_value)

def _is_pydantic_model(schema: object) -> bool:
    """判断是否为pydantic模型"""
    return (isinstance(schema, type) and issubclass(schema, BaseModel))

def _to_json_object(value: object) -> JsonObject:
    """将值转换为JsonObject"""
    if not isinstance(value, dict):
        raise TypeError("Structured output must be a JSON object.")
    return cast(JsonObject, value)
