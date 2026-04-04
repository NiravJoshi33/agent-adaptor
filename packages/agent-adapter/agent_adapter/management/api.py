"""FastAPI management API for local provider operations."""

from __future__ import annotations

import hmac
import json
import os
from hashlib import sha256

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from starlette.responses import JSONResponse, PlainTextResponse

from agent_adapter.management.dashboard import mount_dashboard
from agent_adapter.runtime import RuntimeContext


class CapabilityPricingRequest(BaseModel):
    model: str
    amount: float
    currency: str = "USDC"
    item_field: str = ""
    floor: float = 0.0
    ceiling: float = 0.0


class PromptUpdateRequest(BaseModel):
    custom_prompt: str | None = None
    append_to_default: bool | None = None


class PlatformAddRequest(BaseModel):
    url: str
    name: str = ""
    driver: str = ""


class WalletImportRequest(BaseModel):
    secret_key: str


class WalletExportRequest(BaseModel):
    token: str = ""


class ManagementSessionRequest(BaseModel):
    token: str = ""


def _is_loopback_host(host: str) -> bool:
    normalized = host.strip().lower()
    return normalized in {"127.0.0.1", "localhost", "::1"}


def _management_token(runtime: RuntimeContext) -> str:
    configured = str(runtime.config.get("adapter", {}).get("managementToken", "") or "")
    if configured:
        return configured
    return os.environ.get("AGENT_ADAPTER_MANAGEMENT_TOKEN", "")


def _management_session_value(management_token: str) -> str:
    return hmac.new(
        management_token.encode(),
        b"agent-adapter-management-session-v1",
        sha256,
    ).hexdigest()


def _extract_management_header_token(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() == "bearer" and token:
        return token
    return request.headers.get("x-management-token", "")


def _extract_management_session(request: Request) -> str:
    return request.cookies.get("agent_adapter_management_session", "")


def _is_local_management_request(request: Request) -> bool:
    request_host = request.url.hostname or ""
    client_host = request.client.host if request.client else ""
    host_is_loopback = _is_loopback_host(request_host)
    client_is_loopback = not client_host or _is_loopback_host(client_host)
    return host_is_loopback and client_is_loopback


def create_management_app(runtime: RuntimeContext) -> FastAPI:
    bind_host = str(
        runtime.config.get("adapter", {}).get("dashboard", {}).get("bind", "127.0.0.1")
        or "127.0.0.1"
    )
    allow_unsafe = bool(
        runtime.config.get("adapter", {}).get("allowUnsafeRemoteManagement", False)
    )
    management_token = _management_token(runtime)
    if not _is_loopback_host(bind_host) and not management_token and not allow_unsafe:
        raise ValueError(
            "Remote management requires adapter.managementToken "
            "(or AGENT_ADAPTER_MANAGEMENT_TOKEN), unless allowUnsafeRemoteManagement is explicitly enabled."
        )

    app = FastAPI(
        title="Agent Adapter Management API",
        version="0.1.0",
        docs_url="/manage/docs",
        openapi_url="/manage/openapi.json",
    )

    if management_token:
        @app.middleware("http")
        async def require_management_token(request: Request, call_next):
            path = request.url.path
            if not (path.startswith("/manage") or path.startswith("/dashboard")):
                return await call_next(request)
            if path == "/manage/session":
                return await call_next(request)

            provided = _extract_management_header_token(request)
            session = _extract_management_session(request)
            expected_session = _management_session_value(management_token)
            if not (
                provided and hmac.compare_digest(provided, management_token)
            ) and not (
                session and hmac.compare_digest(session, expected_session)
            ):
                return JSONResponse(
                    {"detail": "Management token required"},
                    status_code=401,
                )
            return await call_next(request)

    else:
        @app.middleware("http")
        async def require_local_management(request: Request, call_next):
            path = request.url.path
            if not (path.startswith("/manage") or path.startswith("/dashboard")):
                return await call_next(request)
            if allow_unsafe or _is_local_management_request(request):
                return await call_next(request)
            return JSONResponse(
                {
                    "detail": (
                        "Remote management requires adapter.managementToken "
                        "or allowUnsafeRemoteManagement."
                    )
                },
                status_code=403,
            )

    mount_dashboard(app, runtime)

    @app.post("/manage/session")
    async def create_management_session(
        request: ManagementSessionRequest, raw_request: Request
    ):
        if not management_token:
            raise HTTPException(
                status_code=400,
                detail="Management session login requires adapter.managementToken",
            )
        if not request.token or not hmac.compare_digest(request.token, management_token):
            raise HTTPException(status_code=401, detail="Management token required")
        response = JSONResponse({"authenticated": True})
        response.set_cookie(
            "agent_adapter_management_session",
            _management_session_value(management_token),
            httponly=True,
            secure=raw_request.url.scheme == "https",
            samesite="lax",
        )
        return response

    @app.get("/manage/status")
    async def get_status():
        return await runtime.whoami()

    @app.get("/manage/wallet")
    async def get_wallet():
        return await runtime.get_wallet_overview()

    @app.post("/manage/wallet/export")
    async def export_wallet(request: WalletExportRequest):
        try:
            await runtime.validate_wallet_export_token(request.token)
            return await runtime.export_wallet_secret()
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except NotImplementedError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.put("/manage/wallet/import")
    async def import_wallet(request: WalletImportRequest):
        try:
            result = await runtime.import_wallet_secret(request.secret_key)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {**result, "restart_required": True}

    @app.get("/manage/capabilities")
    async def list_capabilities():
        return {"capabilities": await runtime.list_capabilities()}

    @app.post("/manage/capabilities/refresh")
    async def refresh_capabilities():
        return {"capabilities": await runtime.refresh_capabilities()}

    @app.put("/manage/capabilities/{name}/pricing")
    async def update_capability_pricing(name: str, request: CapabilityPricingRequest):
        try:
            return await runtime.set_capability_pricing(
                name,
                model=request.model,
                amount=request.amount,
                currency=request.currency,
                item_field=request.item_field,
                floor=request.floor,
                ceiling=request.ceiling,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown capability: {name}") from exc

    @app.post("/manage/capabilities/{name}/enable")
    async def enable_capability(name: str):
        try:
            return await runtime.set_capability_enabled(name, True)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown capability: {name}") from exc

    @app.post("/manage/capabilities/{name}/disable")
    async def disable_capability(name: str):
        try:
            return await runtime.set_capability_enabled(name, False)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown capability: {name}") from exc

    @app.get("/manage/jobs")
    async def list_jobs(limit: int = 20):
        return {"jobs": await runtime.list_jobs(limit)}

    @app.get("/manage/events")
    async def get_events(
        source_type: str = "",
        channel: str = "",
        limit: int = 20,
        pending_only: bool = True,
        acknowledge: bool = False,
    ):
        return {
            "events": await runtime.list_inbound_events(
                source_type=source_type or None,
                channel=channel or None,
                limit=limit,
                pending_only=pending_only,
                acknowledge=acknowledge,
            )
        }

    @app.get("/manage/operations")
    async def get_operations():
        return await runtime.get_operations_overview()

    @app.get("/manage/metrics")
    async def get_metrics(days: int = 30):
        return await runtime.get_metrics_summary(days)

    @app.get("/manage/metrics/export", response_class=PlainTextResponse)
    async def export_metrics(days: int = 30, format: str = "csv"):
        return await runtime.export_metrics(days, format)

    @app.get("/manage/metrics/timeseries")
    async def get_metrics_timeseries(days: int = 14):
        return {"series": await runtime.get_metrics_timeseries(days)}

    @app.get("/manage/platforms")
    async def list_platforms():
        return {"platforms": await runtime.list_platforms()}

    @app.post("/manage/platforms")
    async def add_platform(request: PlatformAddRequest):
        try:
            return await runtime.add_platform(
                request.url,
                platform_name=request.name,
                driver=request.driver,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown driver: {request.driver}") from exc

    @app.get("/manage/drivers")
    async def list_drivers():
        return {"drivers": await runtime.list_drivers()}

    @app.get("/manage/agent/decisions")
    async def list_decisions(limit: int = 50):
        return {"decisions": await runtime.list_decisions(limit)}

    @app.get("/manage/agent/prompt")
    async def get_agent_prompt():
        return await runtime.get_prompt_settings()

    @app.put("/manage/agent/prompt")
    async def update_agent_prompt(request: PromptUpdateRequest):
        return await runtime.update_prompt_settings(
            custom_prompt=request.custom_prompt,
            append_to_default=request.append_to_default,
        )

    @app.post("/manage/agent/pause")
    async def pause_agent():
        return await runtime.pause_agent()

    @app.post("/manage/agent/resume")
    async def resume_agent():
        return await runtime.resume_agent()

    @app.post("/webhooks/{channel}")
    async def receive_webhook(channel: str, request: Request):
        raw = await request.body()
        payload: object
        try:
            payload = json.loads(raw.decode()) if raw else {}
        except Exception:
            payload = raw.decode(errors="replace")
        headers = {k: v for k, v in request.headers.items()}
        event_type = (
            headers.get("x-event-type")
            or request.query_params.get("event")
            or (payload.get("type") if isinstance(payload, dict) else "")
            or "webhook"
        )
        event = await runtime.record_inbound_event(
            source_type="webhook",
            source=str(request.url),
            channel=channel,
            event_type=str(event_type),
            payload=payload,
            headers=headers,
        )
        return {"received": True, "event_id": event["id"], "channel": channel}

    return app
