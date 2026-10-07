from __future__ import annotations

import csv
from dataclasses import dataclass
from io import StringIO


ARTIFACT_THRESHOLD = 128 * 1024
ARTIFACT_CHUNK_SIZE = 16 * 1024


@dataclass(frozen=True)
class OrderRecord:
    """订单测试记录。"""

    order_id: str
    customer_id: str
    customer_name: str
    status: str
    amount: str
    created_at: str
    note: str

    def as_row(self) -> list[str]:
        return [
            self.order_id,
            self.customer_id,
            self.customer_name,
            self.status,
            self.amount,
            self.created_at,
            self.note,
        ]


@dataclass(frozen=True)
class OrderArtifactScenario:
    """大型订单 Artifact 场景数据及预期结果。"""

    content: str
    expected_orders: tuple[OrderRecord, ...]
    split_order_id: str
    split_row_start: int
    split_boundary_offset: int

    @property
    def size(self) -> int:
        return len(self.content.encode("utf-8"))

    @property
    def expected_order_ids(self) -> set[str]:
        return {order.order_id for order in self.expected_orders}


def build_order_artifact_scenario(
    row_count: int = 2400,
) -> OrderArtifactScenario:
    """
    构建确定性的大型订单查询结果。

    目标条件为 ``status == "failed" and amount >= 9000``。数据包含：
    - 超过 Tool Artifact 阈值的 CSV 内容；
    - 分布在文件前、中、后部的目标订单；
    - 中文客户名称；
    - 一条刻意跨越读取块边界的目标订单。
    """
    if row_count < 1800:
        raise ValueError("row_count must be greater than or equal to 1800")

    header = [
        "order_id",
        "customer_id",
        "customer_name",
        "status",
        "amount",
        "created_at",
        "note",
    ]
    parts = [_render_row(header)]
    expected_orders: list[OrderRecord] = []
    target_indexes = {17, 911, 1777}

    for index in range(1, row_count + 1):
        if index == 600:
            _append_boundary_split_order(parts, expected_orders)

        is_target = index in target_indexes
        status = "failed" if is_target or index % 13 == 0 else "success"
        amount = f"{9200 + index / 100:.2f}" if is_target else f"{100 + index % 8000:.2f}"
        customer_number = index % 137
        customer_name = (
            f"客户{customer_number:03d}"
            if index % 10 == 0 or is_target
            else f"Customer {customer_number:03d}"
        )
        order = OrderRecord(
            order_id=f"ORD-{index:05d}",
            customer_id=f"C{customer_number:03d}",
            customer_name=customer_name,
            status=status,
            amount=amount,
            created_at=f"2026-01-{index % 28 + 1:02d}T{index % 24:02d}:00:00+08:00",
            note=f"deterministic-order-{index:05d}-" + "x" * 36,
        )
        parts.append(_render_row(order.as_row()))
        if is_target:
            expected_orders.append(order)

    content = "".join(parts)
    encoded = content.encode("utf-8")
    split_order_id = "ORD-SPLIT"
    split_marker = f"{split_order_id},".encode("utf-8")
    split_row_start = encoded.index(split_marker)
    split_boundary_offset = (
        split_row_start // ARTIFACT_CHUNK_SIZE + 1
    ) * ARTIFACT_CHUNK_SIZE
    split_row_end = encoded.index(b"\n", split_row_start)

    if len(encoded) <= ARTIFACT_THRESHOLD:
        raise AssertionError("scenario data must exceed the artifact threshold")
    if not split_row_start < split_boundary_offset < split_row_end:
        raise AssertionError("split order must cross an artifact chunk boundary")

    return OrderArtifactScenario(
        content=content,
        expected_orders=tuple(expected_orders),
        split_order_id=split_order_id,
        split_row_start=split_row_start,
        split_boundary_offset=split_boundary_offset,
    )


def _append_boundary_split_order(
    parts: list[str],
    expected_orders: list[OrderRecord],
) -> None:
    """对齐下一条目标订单，使其跨越 16 KB 读取边界。"""
    current_size = len("".join(parts).encode("utf-8"))
    desired_start = ARTIFACT_CHUNK_SIZE - 24
    alignment = OrderRecord(
        order_id="ORD-ALIGN",
        customer_id="C000",
        customer_name="Alignment",
        status="success",
        amount="1.00",
        created_at="2026-01-01T00:00:00+08:00",
        note="",
    )
    alignment_without_padding = _render_row(alignment.as_row())
    fixed_size = len(alignment_without_padding.encode("utf-8"))
    padding_size = (
        desired_start - (current_size + fixed_size) % ARTIFACT_CHUNK_SIZE
    ) % ARTIFACT_CHUNK_SIZE
    alignment = OrderRecord(
        order_id=alignment.order_id,
        customer_id=alignment.customer_id,
        customer_name=alignment.customer_name,
        status=alignment.status,
        amount=alignment.amount,
        created_at=alignment.created_at,
        note="p" * padding_size,
    )
    parts.append(_render_row(alignment.as_row()))

    split_order = OrderRecord(
        order_id="ORD-SPLIT",
        customer_id="C042",
        customer_name="边界测试客户",
        status="failed",
        amount="9999.99",
        created_at="2026-01-15T12:30:00+08:00",
        note="target-order-crossing-chunk-boundary",
    )
    parts.append(_render_row(split_order.as_row()))
    expected_orders.append(split_order)


def _render_row(row: list[str]) -> str:
    buffer = StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(row)
    return buffer.getvalue()
