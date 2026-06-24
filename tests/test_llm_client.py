import os
from pathlib import Path

from dotenv import load_dotenv

from echo_agent.core.llm import LLMClient, LLMConfig
from echo_agent.core.model import UserInput


def build_config():
    return LLMConfig(
        base_url=os.getenv("BASE_URL"),
        api_key=os.getenv("API_KEY"),
        model_name=os.getenv("MODEL_NAME"),
        model_provider=os.getenv("MODEL_PROVIDER", "openai"),
        temperature=float(os.getenv("TEMPERATURE", 0.2)),
        max_tokens=int(os.getenv("MAX_TOKENS", 512)),
        timeout=int(os.getenv("TIMEOUT", 60)),
        max_retries=int(os.getenv("MAX_RETRIES", 2)),
    )


def test_llm_invoke():
    config = build_config()
    llm = LLMClient(config)

    history = []

    print("\n==============================")
    print("TEST: LLM INVOKE")
    print("==============================\n")

    while True:
        user_text = input("You: ")

        if user_text.lower() in ["exit", "quit"]:
            break

        result = llm.invoke(
            prompt="You are a helpful assistant. Be concise.",
            user_input=UserInput(text=user_text),
            history=history,
        )
        print("\nAssistant:")
        print(result.content)

        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": result.content})

        print("\n------------------------------\n")


def test_llm_stream():
    config = build_config()
    llm = LLMClient(config)

    history = []

    print("\n==============================")
    print("TEST: LLM STREAM")
    print("==============================\n")

    while True:
        user_text = input("You: ")

        if user_text.lower() in ["exit", "quit"]:
            break

        print("\nAssistant (streaming):")

        full_text = ""
        for chunk in llm.stream(
            prompt="You are a helpful assistant. Be concise.",
            user_input=UserInput(text=user_text),
            history=history,
        ):
            content = getattr(chunk, "content", "")
            print(content, end="", flush=True)
            full_text += content

        print("\n")

        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": full_text})

        print("\n------------------------------\n")


if __name__ == "__main__":
    load_dotenv(Path(__file__).resolve().parent / ".env")
    mode = input("Choose mode (invoke=0 / stream=1): ").strip()
    if mode == "1":
        test_llm_stream()
    else:
        test_llm_invoke()