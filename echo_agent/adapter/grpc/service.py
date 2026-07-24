"""gRPC EchoAgentService 实现：协议 → AgentRuntime。"""

from __future__ import annotations

import json
from typing import Any

import grpc

from ..agent_runtime import AgentRuntime
from ..convert import (
    agent_config_from_proto,
    agent_event_to_proto,
    agent_response_to_proto,
    runtime_options_from_proto,
    user_input_from_proto,
)
from .pb import echo_agent_pb2 as pb
from .pb import echo_agent_pb2_grpc as pb_grpc


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
        except ValueError as exc:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        except Exception as exc:  # noqa: BLE001
            await context.abort(grpc.StatusCode.INTERNAL, f"CreateAgent failed: {exc}")

    async def Invoke(self, request: pb.InvokeRequest, context: grpc.aio.ServicerContext):
        try:
            agent_id, session_id, user_input = self._parse_invoke(request)
            result = await self._runtime.invoke(agent_id, session_id, user_input)
            return agent_response_to_proto(
                output=result.output,
                interrupted=result.interrupted,
                interrupt_payload=result.interrupt_payload,
            )
        except grpc.aio.AbortError:
            raise
        except KeyError as exc:
            await context.abort(grpc.StatusCode.NOT_FOUND, str(exc))
        except ValueError as exc:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        except Exception as exc:  # noqa: BLE001
            await context.abort(grpc.StatusCode.INTERNAL, f"Invoke failed: {exc}")

    async def Stream(self, request: pb.InvokeRequest, context: grpc.aio.ServicerContext):
        try:
            agent_id, session_id, user_input = self._parse_invoke(request)
            async for event in self._runtime.stream(agent_id, session_id, user_input):
                yield agent_event_to_proto(event.type, event.data)
        except grpc.aio.AbortError:
            raise
        except KeyError as exc:
            await context.abort(grpc.StatusCode.NOT_FOUND, str(exc))
        except ValueError as exc:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        except Exception as exc:  # noqa: BLE001
            await context.abort(grpc.StatusCode.INTERNAL, f"Stream failed: {exc}")

    async def Resume(self, request: pb.ResumeRequest, context: grpc.aio.ServicerContext):
        try:
            agent_id, session_id, values = self._parse_resume(request)
            result = await self._runtime.resume(agent_id, session_id, values)
            return agent_response_to_proto(
                output=result.output,
                interrupted=result.interrupted,
                interrupt_payload=result.interrupt_payload,
            )
        except grpc.aio.AbortError:
            raise
        except KeyError as exc:
            await context.abort(grpc.StatusCode.NOT_FOUND, str(exc))
        except ValueError as exc:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        except Exception as exc:  # noqa: BLE001
            await context.abort(grpc.StatusCode.INTERNAL, f"Resume failed: {exc}")

    async def StreamResume(self, request: pb.ResumeRequest, context: grpc.aio.ServicerContext):
        try:
            agent_id, session_id, values = self._parse_resume(request)
            async for event in self._runtime.stream_resume(agent_id, session_id, values):
                yield agent_event_to_proto(event.type, event.data)
        except grpc.aio.AbortError:
            raise
        except KeyError as exc:
            await context.abort(grpc.StatusCode.NOT_FOUND, str(exc))
        except ValueError as exc:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        except Exception as exc:  # noqa: BLE001
            await context.abort(grpc.StatusCode.INTERNAL, f"StreamResume failed: {exc}")

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
        return agent_id, session_id, user_input_from_proto(request.input)

    @staticmethod
    def _parse_resume(request: pb.ResumeRequest) -> tuple[str, str, dict[str, Any]]:
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
        return agent_id, session_id, values
