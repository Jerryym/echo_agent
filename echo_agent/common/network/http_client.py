from typing import Any

import requests

from .exception import HttpRequestError, HttpResponseError

class HttpClient:
    """
    通用 HTTP 客户端

    职责:
        - HTTP 请求封装
        - 统一处理异常
        - 提供基础 GET/POST 能力
    """
    # 默认超时时间
    DEFAULT_TIMEOUT = 10

    @staticmethod
    def get(url: str, headers: dict[str, str] | None = None, timeout: float = DEFAULT_TIMEOUT) -> str:
        """
        GET 请求
        """
        try:
            response = requests.get(
                url,
                headers=headers,
                timeout=timeout,
            )
        except requests.RequestException as e:
            raise HttpRequestError(
                f"HTTP request failed: {url}"
            ) from e

        if not response.ok:
            raise HttpResponseError(
                f"HTTP response error: "
                f"{response.status_code}, url={url}"
            )

        return response.text

    @staticmethod
    def get_json(url: str, headers: dict[str, str] | None = None, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
        """
        GET JSON 请求
        """
        try:
            response = requests.get(
                url,
                headers=headers,
                timeout=timeout,
            )
        except requests.RequestException as e:
            raise HttpRequestError(
                f"HTTP request failed: {url}"
            ) from e

        if not response.ok:
            raise HttpResponseError(
                f"HTTP response error: "
                f"{response.status_code}, url={url}"
            )

        return response.json()

    @staticmethod
    def post(url: str, data: Any = None, json: Any = None, headers: dict[str, str] | None = None, timeout: float = DEFAULT_TIMEOUT) -> str:
        """
        POST 请求
        """
        try:
            response = requests.post(
                url,
                data=data,
                json=json,
                headers=headers,
                timeout=timeout,
            )
        except requests.RequestException as e:
            raise HttpRequestError(
                f"HTTP request failed: {url}"
            ) from e

        if not response.ok:
            raise HttpResponseError(
                f"HTTP response error: "
                f"{response.status_code}, url={url}"
            )

        return response.text
