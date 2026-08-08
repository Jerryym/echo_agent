"""
LLM content / reasoning 交互式真实联调（读取 tests/.env）

运行:
  python tests/test_llm_content.py

建议开启 thinking（否则 reasoning 常为空，将回退展示 content）:
  EXTRA_BODY={"enable_thinking": true}
"""

from __future__ import annotations

import json
from pathlib import Path

from dotenv import load_dotenv

from echo_agent import LLMClient, Message, Role, UserInput
from echo_agent.adapter.events import map_stream_chunk

from env_config import build_config


def _preview(value: object, limit: int = 2000) -> str:
    text = repr(value)
    if len(text) > limit:
        return text[:limit] + "...(truncated)"
    return text


def _dump_raw(raw: object | None) -> None:
    print("\n[raw]")
    if raw is None:
        print("  None")
        return
    print(f"  type={type(raw).__name__}")
    content = getattr(raw, "content", None)
    print(f"  content type={type(content).__name__}")
    print(f"  content={_preview(content)}")
    meta = getattr(raw, "response_metadata", None)
    if meta:
        print(f"  response_metadata={_preview(meta)}")
    extra = getattr(raw, "additional_kwargs", None)
    if extra:
        print(f"  additional_kwargs={_preview(extra)}")


def _print_result_payload(*, content: str, reasoning: str) -> None:
    """有 reasoning 打印 reasoning；否则打印 content。"""
    if reasoning:
        print(f"\n[reasoning]\n{reasoning}")
        if content:
            print(f"\n[content]\n{content}")
    else:
        print(f"\n[content] (no reasoning, fallback)\n{content or '(empty)'}")


def _print_adapter_events(raw: object | None) -> None:
    if raw is None:
        return
    events = map_stream_chunk(raw)
    print("\n[adapter events]")
    if not events:
        print("  (none)")
        return
    for event in events:
        print(f"  type={event.type} data={json.dumps(event.data, ensure_ascii=False)[:500]}")


def chat_invoke(llm: LLMClient) -> None:
    print("\n==============================")
    print("TEST: LLM INVOKE (reasoning/content)")
    print("==============================\n")

    history: list[Message] = []
    while True:
        user_text = input("You: ")
        if user_text.lower() in {"exit", "quit"}:
            break

        result = llm.invoke(
            prompt="You are a helpful assistant. Think carefully when needed.",
            user_input=UserInput(text=user_text),
            history=history,
        )
        _print_result_payload(content=result.content, reasoning=result.reasoning)
        _dump_raw(result.raw)
        _print_adapter_events(result.raw)

        history.append(Message(role=Role.USER, content=user_text))
        history.append(
            Message(
                role=Role.ASSISTANT,
                content=result.content or result.reasoning,
            )
        )
        print("\n------------------------------\n")


def chat_stream(llm: LLMClient) -> None:
    print("\n==============================")
    print("TEST: LLM STREAM (reasoning/content)")
    print("==============================\n")

    history: list[Message] = []
    while True:
        user_text = input("You: ")
        if user_text.lower() in {"exit", "quit"}:
            break

        full_content = ""
        full_reasoning_parts: list[str] = []
        last_raw = None

        print("\nAssistant:")
        for chunk in llm.stream(
            prompt="You are a helpful assistant. Think carefully when needed.",
            user_input=UserInput(text=user_text),
            history=history,
        ):
            last_raw = chunk.raw
            if chunk.reasoning:
                full_reasoning_parts.append(chunk.reasoning)
                print(f"\n[reasoning chunk]\n{chunk.reasoning}", flush=True)
            elif chunk.content:
                # 无 reasoning 时发送/展示 content
                print(chunk.content, end="", flush=True)
                full_content += chunk.content

            if chunk.raw is not None:
                for event in map_stream_chunk(chunk.raw):
                    if event.type == "reasoning":
                        print(
                            f"\n[event:reasoning] {event.data.get('text', '')[:300]}",
                            flush=True,
                        )
                    elif event.type == "message" and event.data.get("content"):
                        # stream 下 message 可能与上面 content 重复，仅作对照
                        pass

        joined_reasoning = "\n".join(full_reasoning_parts).strip()
        print()
        _print_result_payload(content=full_content, reasoning=joined_reasoning)
        _dump_raw(last_raw)

        history.append(Message(role=Role.USER, content=user_text))
        history.append(
            Message(
                role=Role.ASSISTANT,
                content=full_content or joined_reasoning,
            )
        )
        print("\n------------------------------\n")


if __name__ == "__main__":
    load_dotenv(Path(__file__).resolve().parent / ".env")
    config = build_config()
    print(
        f"model={config.model_name} provider={config.model_provider} "
        f"extra_body={config.extra_body} responses_api={config.use_responses_api}"
    )
    llm = LLMClient(config)
    mode = input("Choose mode (invoke=0 / stream=1): ").strip()
    if mode == "1":
        chat_stream(llm)
    else:
        chat_invoke(llm)
