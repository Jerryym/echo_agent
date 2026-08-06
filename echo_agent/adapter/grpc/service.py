"""gRPC EchoAgentService 实现：协议 → AgentRuntime。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import grpc

from ...common import get_logger
from ..agent_runtime import AgentLimitExceededError, AgentRuntime
from ..convert import (
    agent_config_from_proto,
    agent_event_to_proto,
    agent_response_to_proto,
    runtime_options_from_proto,
    user_input_from_proto,
)
from .pb import echo_agent_pb2 as pb
from .pb import echo_agent_pb2_grpc as pb_grpc

logger = get_logger("adapter.grpc")


def _internal_message(operation: str) -> str:
    """对外 INTERNAL 短文案（不附带异常原文）。"""
    return f"{operation} failed"


class EchoAgentServicer(pb_grpc.EchoAgentServiceServicer):
    def __init__(self, runtime: AgentRuntime) -> None:
        self._runtime = runtime

    async def CreateAgent(self, request: pb.CreateAgentRequest, context: grpc.aio.ServicerContext):
        try:
            if not request.HasField("config"):
                await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "config is required")
            config = agent_config_from_proto(request.config)
            options = None
            if request.HasField("runtime_options"):
                options = runtime_options_from_proto(request.runtime_options)
            agent_id = await self._runtime.create_agent(config, options)
            return pb.AgentHandle(id=agent_id)
        except grpc.aio.AbortError:
            raise
        except AgentLimitExceededError as exc:
            await context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, str(exc))
        except ValueError as exc:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        except Exception:  # noqa: BLE001
            logger.exception("CreateAgent failed")
            await context.abort(grpc.StatusCode.INTERNAL, _internal_message("CreateAgent"))

    async def DeleteAgent(self, request: pb.DeleteAgentRequest, context: grpc.aio.ServicerContext):
        try:
            agent_id = (request.agent_id or "").strip()
            if not agent_id:
                await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "agent_id is required")
            await self._runtime.delete_agent(agent_id)
            return pb.DeleteAgentResponse()
        except grpc.aio.AbortError:
            raise
        except KeyError as exc:
            await context.abort(grpc.StatusCode.NOT_FOUND, str(exc))
        except Exception:  # noqa: BLE001
            logger.exception("DeleteAgent failed")
            await context.abort(grpc.StatusCode.INTERNAL, _internal_message("DeleteAgent"))

    async def Invoke(self, request: pb.InvokeRequest, context: grpc.aio.ServicerContext):
        try:
            agent_id, session_id, user_input, metadata = self._parse_invoke(request)
            result = await self._runtime.invoke(
                agent_id, session_id, user_input, metadata=metadata
            )
            return agent_response_to_proto(
                output=result.output,
                interrupted=result.interrupted,
                interrupt_payload=result.interrupt_payload,
            )
        except grpc.aio.AbortError:
            raise
        except asyncio.CancelledError:
            await self._abort_if_turn_cancelled(context)
            raise
        except KeyError as exc:
            await context.abort(grpc.StatusCode.NOT_FOUND, str(exc))
        except ValueError as exc:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        except RuntimeError as exc:
            await context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(exc))
        except Exception:  # noqa: BLE001
            logger.exception("Invoke failed")
            await context.abort(grpc.StatusCode.INTERNAL, _internal_message("Invoke"))

    async def Stream(self, request: pb.InvokeRequest, context: grpc.aio.ServicerContext):
        agent_id = ""
        session_id = ""
        try:
            agent_id, session_id, user_input, metadata = self._parse_invoke(request)
            async for event in self._runtime.stream(
                agent_id, session_id, user_input, metadata=metadata
            ):
                if context.cancelled():
                    break
                yield agent_event_to_proto(event.type, event.data)
                if event.type == "error":
                    # 方案 B：已下发 error 事件，再以非 OK 结束 RPC
                    await context.abort(
                        grpc.StatusCode.INTERNAL,
                        _internal_message("Stream"),
                    )
            if context.cancelled():
                await self._ensure_cancelled(agent_id, session_id)
                yield agent_event_to_proto("cancelled", {})
                await context.abort(grpc.StatusCode.CANCELLED, "cancelled")
        except grpc.aio.AbortError:
            raise
        except asyncio.CancelledError:
            await self._ensure_cancelled(agent_id, session_id)
            if context.cancelled():
                raise
            # Cancel RPC 中止当轮，Stream 客户端仍在：下发 cancelled 并以 CANCELLED 结束
            yield agent_event_to_proto("cancelled", {})
            await context.abort(grpc.StatusCode.CANCELLED, "cancelled")
        except KeyError as exc:
            await context.abort(grpc.StatusCode.NOT_FOUND, str(exc))
        except ValueError as exc:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        except RuntimeError as exc:
            await context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(exc))
        except Exception:  # noqa: BLE001
            logger.exception("Stream failed")
            await context.abort(grpc.StatusCode.INTERNAL, _internal_message("Stream"))

    async def Resume(self, request: pb.ResumeRequest, context: grpc.aio.ServicerContext):
        try:
            agent_id, session_id, values, metadata = self._parse_resume(request)
            result = await self._runtime.resume(
                agent_id, session_id, values, metadata=metadata
            )
            return agent_response_to_proto(
                output=result.output,
                interrupted=result.interrupted,
                interrupt_payload=result.interrupt_payload,
            )
        except grpc.aio.AbortError:
            raise
        except asyncio.CancelledError:
            await self._abort_if_turn_cancelled(context)
            raise
        except KeyError as exc:
            await context.abort(grpc.StatusCode.NOT_FOUND, str(exc))
        except ValueError as exc:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        except RuntimeError as exc:
            await context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(exc))
        except Exception:  # noqa: BLE001
            logger.exception("Resume failed")
            await context.abort(grpc.StatusCode.INTERNAL, _internal_message("Resume"))

    async def StreamResume(self, request: pb.ResumeRequest, context: grpc.aio.ServicerContext):
        agent_id = ""
        session_id = ""
        try:
            agent_id, session_id, values, metadata = self._parse_resume(request)
            async for event in self._runtime.stream_resume(
                agent_id, session_id, values, metadata=metadata
            ):
                if context.cancelled():
                    break
                yield agent_event_to_proto(event.type, event.data)
                if event.type == "error":
                    await context.abort(
                        grpc.StatusCode.INTERNAL,
                        _internal_message("StreamResume"),
                    )
            if context.cancelled():
                await self._ensure_cancelled(agent_id, session_id)
                yield agent_event_to_proto("cancelled", {})
                await context.abort(grpc.StatusCode.CANCELLED, "cancelled")
        except grpc.aio.AbortError:
            raise
        except asyncio.CancelledError:
            await self._ensure_cancelled(agent_id, session_id)
            if context.cancelled():
                raise
            yield agent_event_to_proto("cancelled", {})
            await context.abort(grpc.StatusCode.CANCELLED, "cancelled")
        except KeyError as exc:
            await context.abort(grpc.StatusCode.NOT_FOUND, str(exc))
        except ValueError as exc:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        except RuntimeError as exc:
            await context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(exc))
        except Exception:  # noqa: BLE001
            logger.exception("StreamResume failed")
            await context.abort(grpc.StatusCode.INTERNAL, _internal_message("StreamResume"))

    async def Cancel(self, request: pb.CancelRequest, context: grpc.aio.ServicerContext):
        try:
            agent_id = (request.agent_id or "").strip()
            session_id = (request.session_id or "").strip()
            if not agent_id:
                await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "agent_id is required")
            if not session_id:
                await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "session_id is required")
            cancelled = await self._runtime.cancel(agent_id, session_id)
            return pb.CancelResponse(cancelled=cancelled)
        except grpc.aio.AbortError:
            raise
        except KeyError as exc:
            await context.abort(grpc.StatusCode.NOT_FOUND, str(exc))
        except ValueError as exc:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        except Exception:  # noqa: BLE001
            logger.exception("Cancel failed")
            await context.abort(grpc.StatusCode.INTERNAL, _internal_message("Cancel"))

    async def _ensure_cancelled(self, agent_id: str, session_id: str) -> None:
        """断流 / CancelledError 时确保当轮 Task 取消并回滚（幂等）。"""
        if not agent_id or not session_id:
            return
        try:
            await self._runtime.cancel(agent_id, session_id)
        except Exception:  # noqa: BLE001
            logger.exception(
                "ensure cancel failed agent_id=%s session_id=%s",
                agent_id,
                session_id,
            )

    @staticmethod
    async def _abort_if_turn_cancelled(context: grpc.aio.ServicerContext) -> None:
        """
        Invoke/Resume 任务被 Cancel RPC 取消（客户端 RPC 未断）时，
        以 CANCELLED 结束；若是客户端取消本 RPC，则交由上层 re-raise。
        """
        if context.cancelled():
            return
        await context.abort(grpc.StatusCode.CANCELLED, "cancelled")

    @staticmethod
    def _parse_invoke(request: pb.InvokeRequest):
        agent_id = (request.agent_id or "").strip()
        session_id = (request.session_id or "").strip()
        if not agent_id:
            raise ValueError("agent_id is required")
        if not session_id:
            raise ValueError("session_id is required")
        if not request.HasField("input"):
            raise ValueError("input is required")
        metadata = dict(request.metadata) if request.metadata else None
        return agent_id, session_id, user_input_from_proto(request.input), metadata

    @staticmethod
    def _parse_resume(
        request: pb.ResumeRequest,
    ) -> tuple[str, str, dict[str, Any], dict[str, str] | None]:
        agent_id = (request.agent_id or "").strip()
        session_id = (request.session_id or "").strip()
        if not agent_id:
            raise ValueError("agent_id is required")
        if not session_id:
            raise ValueError("session_id is required")
        raw = request.values_json or ""
        if not raw.strip():
            raise ValueError("values_json is required")
        try:
            values = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"values_json is not valid JSON: {exc}") from exc
        if not isinstance(values, dict):
            raise ValueError("values_json must be a JSON object")
        metadata = dict(request.metadata) if request.metadata else None
        return agent_id, session_id, values, metadata
