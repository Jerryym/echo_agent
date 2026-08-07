"""#5 验收：adapter.convert 不得依赖 gRPC / protobuf。"""

from __future__ import annotations

import ast
from pathlib import Path

import echo_agent.adapter.convert as convert_mod


def test_adapter_convert_source_has_no_grpc_or_pb2_imports():
    path = Path(convert_mod.__file__).resolve()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    forbidden_roots = ("grpc",)
    forbidden_substrings = ("pb2", "echo_agent.adapter.grpc")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                assert not name.startswith(forbidden_roots), name
                for frag in forbidden_substrings:
                    assert frag not in name, name
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert not mod.startswith(forbidden_roots), mod
            for frag in forbidden_substrings:
                assert frag not in mod, mod


def test_adapter_convert_exports_protocol_agnostic_builders():
    assert hasattr(convert_mod, "llm_config_from_fields")
    assert hasattr(convert_mod, "agent_config_from_fields")
    assert hasattr(convert_mod, "user_input_from_fields")
    assert not hasattr(convert_mod, "llm_config_from_proto")
    assert not hasattr(convert_mod, "agent_config_from_proto")
