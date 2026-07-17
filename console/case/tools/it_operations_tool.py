from typing import Literal


def get_server_info(server_id: str) -> dict:
    """
    查询服务器基础信息

    Args:
        server_id: 服务器 ID，例如 srv_001
    """

    servers = {
        "srv_001": {
            "server_id": "srv_001",
            "hostname": "prod-api-01",
            "ip": "10.0.1.20",
            "environment": "production",
            "status": "running",
        },
        "srv_002": {
            "server_id": "srv_002",
            "hostname": "test-web-01",
            "ip": "10.0.2.10",
            "environment": "testing",
            "status": "stopped",
        },
    }

    server = servers.get(server_id)

    if not server:
        return {
            "success": False,
            "error": "server_not_found",
            "server_id": server_id,
        }

    return {
        "success": True,
        "data": server,
    }


def get_service_status(
    server_id: str,
    service_name: str,
) -> dict:
    """
    查询服务器上的服务状态

    Args:
        server_id: 服务器 ID，例如 srv_001
        service_name: 服务名称，例如 nginx、mysql
    """

    services = {
        ("srv_001", "nginx"): {
            "status": "running",
            "port": 80,
        },
        ("srv_001", "mysql"): {
            "status": "running",
            "port": 3306,
        },
        ("srv_002", "nginx"): {
            "status": "stopped",
            "port": 80,
        },
    }

    service = services.get(
        (server_id, service_name)
    )

    if not service:
        return {
            "success": False,
            "error": "service_not_found",
            "server_id": server_id,
            "service_name": service_name,
        }

    return {
        "success": True,
        "data": {
            "server_id": server_id,
            "service_name": service_name,
            **service,
        },
    }


def restart_service(
    server_id: str,
    service_name: str,
) -> dict:
    """
    重启服务器上的指定服务

    Args:
        server_id: 服务器 ID
        service_name: 服务名称
    """

    if server_id not in [
        "srv_001",
        "srv_002",
    ]:
        return {
            "success": False,
            "error": "server_not_found",
        }

    return {
        "success": True,
        "message": (
            f"{service_name} restarted successfully"
        ),
        "server_id": server_id,
        "service_name": service_name,
    }


def create_incident_ticket(
    title: str,
    description: str,
    severity: Literal[
        "low",
        "medium",
        "high",
        "critical",
    ],
) -> dict:
    """
    创建故障工单

    Args:
        title: 故障标题
        description: 故障描述
        severity: 故障等级
    """

    if severity in [
        "high",
        "critical",
    ]:
        return {
            "success": False,
            "status": "need_approval",
            "reason": (
                "high severity ticket "
                "requires human approval"
            ),
        }

    return {
        "success": True,
        "ticket_id": "INC-10001",
        "status": "created",
    }


def get_ticket_status(
    ticket_id: str,
) -> dict:
    """
    查询故障工单状态

    Args:
        ticket_id: 工单编号，例如 INC-10001
    """

    tickets = {
        "INC-10001": {
            "status": "processing",
            "owner": "ops-team",
            "progress": "investigating",
        },
        "INC-10002": {
            "status": "resolved",
            "owner": "ops-team",
            "progress": "completed",
        },
    }

    ticket = tickets.get(ticket_id)

    if not ticket:
        return {
            "success": False,
            "error": "ticket_not_found",
            "ticket_id": ticket_id,
        }

    return {
        "success": True,
        "data": {
            "ticket_id": ticket_id,
            **ticket,
        },
    }


IT_OPERATIONS_TOOLS = [
    get_server_info,
    get_service_status,
    restart_service,
    create_incident_ticket,
    get_ticket_status,
]