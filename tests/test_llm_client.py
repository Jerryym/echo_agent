from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, BaseMessage

from echo_agent import LLMClient, UserInput

from env_config import build_config


def test_llm_invoke():
    config = build_config()
    llm = LLMClient(config)

    history: list[BaseMessage] = []

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

        history.append(UserInput(text=user_text).to_human_message())
        history.append(AIMessage(content=result.content))

        print("\n------------------------------\n")


def test_llm_stream():
    config = build_config()
    llm = LLMClient(config)

    history: list[BaseMessage] = []

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

        history.append(UserInput(text=user_text).to_human_message())
        history.append(AIMessage(content=full_text))

        print("\n------------------------------\n")


if __name__ == "__main__":
    load_dotenv(Path(__file__).resolve().parent / ".env")
    mode = input("Choose mode (invoke=0 / stream=1): ").strip()
    if mode == "1":
        test_llm_stream()
    else:
        test_llm_invoke()