from typing import Any

from langchain_core.tools import tool


# =========================
# Mock Data
# =========================

_USERS = {
    "u001": {
        "name": "张伟",
        "department": "研发部",
        "level": "P7",
        "status": "active",
    },
    "u002": {
        "name": "李娜",
        "department": "销售部",
        "level": "P5",
        "status": "active",
    },
}


_ORDERS = {
    "order_1001": {
        "user_id": "u001",
        "amount": 2999,
        "status": "paid",
    },
    "order_1002": {
        "user_id": "u001",
        "amount": 599,
        "status": "shipping",
    },
}


_STOCK = {
    "iphone15": 12,
    "macbook_m3": 3,
    "airpods": 50,
}


_PRICES = {
    "iphone15": 5999,
    "macbook_m3": 12999,
    "airpods": 1299,
}


_SALARY = {
    "u001": 35000,
    "u002": 18000,
}


_REFUNDS: list[dict[str, Any]] = []


_WEATHER = {
    "北京": "晴，25℃",
    "上海": "多云，28℃",
    "深圳": "小雨，30℃",
}


# =========================
# User
# =========================

@tool
def get_user_profile(user_id: str) -> dict[str, Any]:
    """
    根据用户ID查询用户基本信息。

    Args:
        user_id:
            用户唯一ID，例如 u001
    """

    return _USERS.get(
        user_id,
        {
            "error": "user not found",
        },
    )


# =========================
# Order
# =========================

@tool
def get_order_detail(order_id: str) -> dict[str, Any]:
    """
    查询订单详情。

    Args:
        order_id:
            订单编号
    """

    return _ORDERS.get(
        order_id,
        {
            "error": "order not found",
        },
    )


@tool
def create_refund(
    order_id: str,
    reason: str,
) -> dict[str, Any]:
    """
    创建退款申请。

    IMPORTANT:
    This tool must be called whenever a user requests
    creating, applying, submitting or processing a refund.

    This tool only creates a refund request.
    It does not happen automatically.

    Args:
        order_id:
            订单编号

        reason:
            退款原因
    """

    refund = {
        "refund_id": f"refund_{len(_REFUNDS)+1}",
        "order_id": order_id,
        "reason": reason,
        "status": "pending",
    }

    _REFUNDS.append(refund)

    return refund


@tool
def get_refund_status(
    refund_id: str,
) -> dict[str, Any]:
    """
    查询退款状态。

    Args:
        refund_id:
            退款编号
    """

    for refund in _REFUNDS:
        if refund["refund_id"] == refund_id:
            return refund

    return {
        "error": "refund not found",
    }


# =========================
# Product
# =========================

@tool
def query_inventory(
    product_name: str,
) -> dict[str, Any]:
    """
    查询商品库存。

    Args:
        product_name:
            商品名称
    """

    return {
        "product": product_name,
        "stock": _STOCK.get(product_name, 0),
    }


@tool
def query_product_price(
    product_name: str,
) -> dict[str, Any]:
    """
    查询商品价格。

    Args:
        product_name:
            商品名称
    """

    price = _PRICES.get(product_name)

    if price is None:
        return {
            "error": "product not found",
        }

    return {
        "product": product_name,
        "price": price,
    }


# =========================
# Employee
# =========================

@tool
def query_salary(
    user_id: str,
) -> dict[str, Any]:
    """
    查询员工月薪。

    Args:
        user_id:
            用户ID
    """

    salary = _SALARY.get(user_id)

    if salary is None:
        return {
            "error": "salary unavailable",
        }

    return {
        "user_id": user_id,
        "monthly_salary": salary,
    }


# =========================
# Finance
# =========================

@tool
def currency_exchange(
    amount: float,
    from_currency: str,
    to_currency: str,
) -> dict[str, Any]:
    """
    汇率转换。

    Args:
        amount:
            金额

        from_currency:
            原货币，例如 USD

        to_currency:
            目标货币，例如 CNY
    """

    rates = {
        ("USD", "CNY"): 7.2,
        ("EUR", "CNY"): 7.8,
    }

    rate = rates.get(
        (
            from_currency,
            to_currency,
        )
    )

    if rate is None:
        return {
            "error": "unsupported exchange",
        }

    return {
        "result": amount * rate,
        "currency": to_currency,
    }


# =========================
# Weather
# =========================

@tool
def query_weather(
    city: str,
) -> str:
    """
    查询城市天气。

    Args:
        city:
            城市名称
    """

    return _WEATHER.get(
        city,
        "unknown city",
    )


# =========================
# Report
# =========================

@tool
def generate_business_report(
    title: str,
    metrics: dict[str, Any],
) -> str:
    """
    根据指标生成业务报告。

    Args:
        title:
            报告标题

        metrics:
            数据指标
    """

    lines = [
        f"# {title}",
    ]

    for key, value in metrics.items():
        lines.append(
            f"- {key}: {value}"
        )

    return "\n".join(lines)

# =========================
# User
# =========================

@tool
def query_user_by_name(
    name: str,
) -> dict[str, Any]:
    """
    根据用户姓名查询用户信息。

    This tool should be used before querying user-related data
    when only the user's name is available.

    Args:
        name:
            用户姓名，例如 张伟
    """

    for user_id, user in _USERS.items():
        if user["name"] == name:
            return {
                "user_id": user_id,
                **user,
            }

    return {
        "error": "user not found",
    }


@tool
def query_user_orders(
    user_id: str,
) -> list[dict[str, Any]]:
    """
    根据用户ID查询该用户所有订单。

    IMPORTANT:
    The user_id must come from a previous user query result.
    Do not guess or infer user_id.

    Args:
        user_id:
            用户唯一ID，例如 u001
    """

    return [
        {
            "order_id": order_id,
            **order,
        }
        for order_id, order in _ORDERS.items()
        if order["user_id"] == user_id
    ]


# =========================
# Export
# =========================

BUSINESS_TOOLS = [
    get_user_profile,
    get_order_detail,
    query_inventory,
    query_product_price,
    create_refund,
    get_refund_status,
    query_salary,
    currency_exchange,
    query_weather,
    generate_business_report,
    query_user_by_name,
    query_user_orders,
]
