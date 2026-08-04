class HttpClientError(Exception):
    """
    HTTP Client 基础异常
    """
    pass


class HttpRequestError(HttpClientError):
    """
    HTTP 请求失败

    包括:
        - 网络不可达
        - DNS失败
        - timeout
        - connection error
    """
    pass


class HttpResponseError(HttpClientError):
    """
    HTTP 响应异常

    包括:
        - 4xx
        - 5xx
    """
    pass