"""RunnableConfig.configurable["metadata"] 保留键与相关约定。

后续同类定义（固定键名、默认形态说明）集中放此文件，供 Agent / Adapter 共用。
"""

from __future__ import annotations

# 保留键：出站 HTTP 请求头；值为 dict[str, str]（方案 B，入口可将 JSON 字符串解析为此形态）
METADATA_HTTP_HEADERS_KEY = "http_headers"
