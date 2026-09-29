from ...model.tool import ToolArtifact


class ToolArtifactManager:
    """
    ToolArtifactManager: 负责将大型工具输出结果导出为临时文件
    """
    def __init__(self):
        pass

    def store(self, content: str) -> ToolArtifact:
        """保存为临时文件"""
        
