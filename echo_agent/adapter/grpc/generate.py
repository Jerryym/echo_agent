"""重新从 proto 生成 Python stubs。

用法（仓库根目录）::

    python -m echo_agent.adapter.grpc.generate
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parents[3]
    proto_dir = repo_root / "echo_agent" / "proto"
    out_dir = Path(__file__).resolve().parent / "pb"
    proto_file = proto_dir / "echo_agent.proto"
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        "-m",
        "grpc_tools.protoc",
        f"-I{proto_dir}",
        f"--python_out={out_dir}",
        f"--grpc_python_out={out_dir}",
        f"--pyi_out={out_dir}",
        str(proto_file),
    ]
    print(" ".join(cmd))
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        return result.returncode

    grpc_file = out_dir / "echo_agent_pb2_grpc.py"
    text = grpc_file.read_text(encoding="utf-8")
    old = "import echo_agent_pb2 as echo__agent__pb2"
    new = "from . import echo_agent_pb2 as echo__agent__pb2"
    if old in text:
        grpc_file.write_text(text.replace(old, new), encoding="utf-8")
        print(f"patched relative import in {grpc_file.name}")
    else:
        print(f"warning: expected import not found in {grpc_file.name}; check manually")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
