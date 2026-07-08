from pathlib import Path


class PromptLoader:
    """
    提示词加载器
    """
    @staticmethod
    def load(path: str | Path) -> str:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Prompt file not found: {path}")
        if not path.is_file():
            raise IsADirectoryError(f"Prompt file is a directory: {path}")
        if not path.suffix == ".md":
            raise ValueError(f"Prompt file is not a markdown file: {path}")
        return path.read_text(encoding="utf-8")