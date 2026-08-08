from pathlib import Path

from dotenv import load_dotenv

from echo_agent import LLMClient, Message, Role, UserInput

from env_config import build_config


def test_llm_invoke():
    config = build_config()
    llm = LLMClient(config)

    history: list[Message] = []

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
        print("--- 思考过程 ---")
        print(result.reasoning or "")

        print("\n--- 最终回答 ---")
        print(result.text)

        history.append(Message(role=Role.USER, content=user_text))
        history.append(Message(role=Role.ASSISTANT, content=result.text))

        print("\n------------------------------\n")


def test_llm_stream():
    config = build_config()
    llm = LLMClient(config)

    history: list[Message] = []

    print("\n==============================")
    print("TEST: LLM STREAM")
    print("==============================\n")

    while True:
        user_text = input("You: ")

        if user_text.lower() in ["exit", "quit"]:
            break

        print("\nAssistant (streaming):")
        print("--- 思考过程 ---")

        full_text = ""
        full_reasoning = ""
        for chunk in llm.stream(
            prompt="You are a helpful assistant. Be concise.",
            user_input=UserInput(text=user_text),
            history=history,
        ):
            if chunk.reasoning:
                print(chunk.reasoning, end="", flush=True)
                full_reasoning += chunk.reasoning
            if chunk.text:
                if full_reasoning and not full_text:
                    print("\n\n--- 最终回答 ---")
                print(chunk.text, end="", flush=True)
                full_text += chunk.text

        print("\n")

        history.append(Message(role=Role.USER, content=user_text))
        history.append(Message(role=Role.ASSISTANT, content=full_text))

        print("\n------------------------------\n")


if __name__ == "__main__":
    load_dotenv(Path(__file__).resolve().parent / ".env")
    mode = input("Choose mode (invoke=0 / stream=1): ").strip()
    if mode == "1":
        test_llm_stream()
    else:
        test_llm_invoke()
