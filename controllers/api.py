import json
from typing import Any, Optional

from core.routing import Request, Response
from core.utils.jwt import JwtUtils
from ..config import CONTRACT_VERSION, MCP_INTERNAL_KEY
from ..contract.errors import (
    AuthenticationRequiredError,
    MCPErrorCode,
    MCPException,
)
from ..services.auditor import MCPAuditor
from ..services.executor import ToolExecutor
from ..services.tool_registry import ToolRegistry
from ..services.api_key_service import MCPApiKeyService


class MCPAPIController:
    """Contrôleur API REST interne pour melodi_mcp_server."""

    @classmethod
    async def _authenticate_request(cls, request: Request) -> Optional[dict[str, Any]]:
        """Authentifie la requête entrante (délègue à resolve_mcp_user)."""
        from ..middlewares import resolve_mcp_user
        return await resolve_mcp_user(request, service_cls=MCPApiKeyService)

    @classmethod
    async def health(cls, request: Request, response: Response):
        """GET /health - État de santé du module melodi_mcp."""
        registry = ToolRegistry.get_instance(app=request.app)
        data = {
            "status": "healthy",
            "module_loaded": True,
            "registry_available": registry is not None,
            "contract_version": CONTRACT_VERSION,
            "revision": registry.get_revision(),
            "tools_count": registry.count(enabled_only=True),
        }
        return response.render_json(data, status_code=200)

    @classmethod
    async def manifest(cls, request: Request, response: Response):
        """GET /manifest - Manifeste de capacités pour melodi_mcp_server."""
        registry = ToolRegistry.get_instance(app=request.app)

        melodi_version = "1.0.0"
        if hasattr(request.app, "config") and hasattr(request.app.config, "VERSION"):
            melodi_version = getattr(request.app.config, "VERSION")

        data = {
            "contract_version": CONTRACT_VERSION,
            "melodi_version": melodi_version,
            "catalog_revision": registry.get_revision(),
            "updated_at": registry.get_updated_at().isoformat(),
            "tools_count": registry.count(enabled_only=True),
            "capabilities": {
                "tools_discovery": True,
                "tool_execution": True,
                "etag_support": True,
                "dynamic_reload": True,
                "streaming": False,
                "batch": False,
            },
            "server_info": {
                "provider": "MELODI ERP melodi_mcp",
                "auth_modes": ["bearer_jwt", "service_key"],
            }
        }
        return response.render_json(data, status_code=200)

    @classmethod
    async def get_revision(cls, request: Request, response: Response):
        """GET /revision - Vérification rapide de changement de catalogue."""
        registry = ToolRegistry.get_instance(app=request.app)
        current_rev = registry.get_revision()

        # Support If-None-Match
        if_none_match = request.headers.get("If-None-Match", "").strip('"')
        if if_none_match and if_none_match == current_rev:
            response.set_header("ETag", f'"{current_rev}"')
            return "", 304

        data = {
            "catalog_revision": current_rev,
            "updated_at": registry.get_updated_at().isoformat(),
            "tools_count": registry.count(enabled_only=True),
        }
        response.set_header("ETag", f'"{current_rev}"')
        return response.render_json(data, status_code=200)

    @classmethod
    async def list_tools(cls, request: Request, response: Response):
        """GET /tools - Découverte du catalogue des outils."""
        # 1. Vérification d'authentification
        user_ctx = await cls._authenticate_request(request)
        if not user_ctx:
            err = AuthenticationRequiredError(
                message="Authentification utilisateur requise : token personnel MCP manquant, invalide ou expiré. Veuillez générer un token dans MELODI > Mes Tokens MCP."
            )
            return response.render_json(err.to_dict(), status_code=err.status_code)

        registry = ToolRegistry.get_instance(app=request.app)
        current_rev = registry.get_revision()

        # Vérification If-None-Match
        if_none_match = request.headers.get("If-None-Match", "").strip('"')
        if if_none_match and if_none_match == current_rev:
            response.set_header("ETag", f'"{current_rev}"')
            return "", 304

        # Filtres
        module_filter = request.query.get("module")
        category_filter = request.query.get("category")
        read_only_param = request.query.get("read_only")
        read_only_filter = None
        if read_only_param is not None:
            read_only_filter = read_only_param.lower() in ("true", "1", "yes")

        all_tools = registry.list_tools(
            module=module_filter,
            category=category_filter,
            read_only=read_only_filter,
            enabled_only=True,
            check_module_active=True,
        )

        # Filtrage des outils selon les permissions de l'utilisateur
        executor = ToolExecutor(registry=registry, app=request.app)
        all_tools = [t for t in all_tools if executor.has_tool_permission(t, user_ctx)]

        # Pagination optionnelle
        try:
            page = max(1, int(request.query.get("page", 1)))
            per_page = max(1, min(100, int(request.query.get("per_page", 50))))
        except (ValueError, TypeError):
            page = 1
            per_page = 50

        total = len(all_tools)
        start_idx = (page - 1) * per_page
        paged_tools = all_tools[start_idx : start_idx + per_page]

        response.set_header("ETag", f'"{current_rev}"')
        return response.render_json({
            "success": True,
            "catalog_revision": current_rev,
            "data": {
                "tools": [t.to_mcp_dict() for t in paged_tools],
                "meta": {
                    "total": total,
                    "page": page,
                    "per_page": per_page,
                    "pages": (total + per_page - 1) // per_page if total > 0 else 1,
                }
            }
        }, status_code=200)

    @classmethod
    async def execute_tool(cls, request: Request, response: Response):
        """POST /tools/<tool_name>/execute ou POST /tools/execute."""
        # 1. Authentification stricte
        user_ctx = await cls._authenticate_request(request)
        if not user_ctx:
            err = AuthenticationRequiredError(
                message="Authentification utilisateur requise : token personnel MCP manquant, invalide ou expiré. Veuillez générer un token dans MELODI > Mes Tokens MCP."
            )
            return response.render_json(err.to_dict(), status_code=err.status_code)

        # 2. Résolution du corps JSON sécurisé
        body = {}
        if hasattr(request, "get_json") and callable(request.get_json):
            raw_body = request.get_json()
            if isinstance(raw_body, dict):
                body = raw_body
        elif isinstance(getattr(request, "json", None), dict):
            body = request.json

        # 3. Résolution du nom d'outil (paramètre d'URL, query string, ou body)
        tool_name = (
            request.params.get("tool_name")
            or request.params.get("name")
            or request.query.get("tool_name")
            or body.get("tool_name")
            or body.get("name")
        )

        if not tool_name:
            return response.render_json({
                "success": False,
                "error": {
                    "code": MCPErrorCode.TOOL_NOT_FOUND.value,
                    "message": "Le nom de l'outil à exécuter est requis.",
                }
            }, status_code=400)
        arguments = body.get("arguments", {})
        correlation_id = body.get("correlation_id") or request.headers.get("X-Correlation-ID")
        confirmed = bool(body.get("confirmed", False))
        business_context = body.get("context", {})

        registry = ToolRegistry.get_instance(app=request.app)
        executor = ToolExecutor(registry=registry, app=request.app)

        result = await executor.execute(
            tool_name=tool_name,
            arguments=arguments,
            user_context=user_ctx,
            correlation_id=correlation_id,
            confirmed=confirmed,
            business_context=business_context,
        )

        status_code = 200 if result.get("success") else 400
        if not result.get("success"):
            err_code = result.get("error", {}).get("code")
            if err_code == MCPErrorCode.TOOL_NOT_FOUND.value:
                status_code = 404
            elif err_code == MCPErrorCode.PERMISSION_DENIED.value:
                status_code = 403
            elif err_code == MCPErrorCode.AUTHENTICATION_REQUIRED.value:
                status_code = 401
            elif err_code == MCPErrorCode.INVALID_ARGUMENTS.value:
                status_code = 422
            elif err_code == MCPErrorCode.MODULE_UNAVAILABLE.value:
                status_code = 503
            elif err_code == MCPErrorCode.EXECUTION_TIMEOUT.value:
                status_code = 504

        return response.render_json(result, status_code=status_code)

    @classmethod
    async def audit_logs(cls, request: Request, response: Response):
        """GET /internal/audit-logs ou /audit-logs - Historique d'audit des exécutions."""
        user_ctx = await cls._authenticate_request(request)
        if not user_ctx:
            err = AuthenticationRequiredError(
                message="Authentification utilisateur requise : token personnel MCP manquant, invalide ou expiré. Veuillez générer un token dans MELODI > Mes Tokens MCP."
            )
            return response.render_json(err.to_dict(), status_code=err.status_code)

        auditor = MCPAuditor(app=request.app)
        registry = ToolRegistry.get_instance(app=request.app)
        all_tools = registry.list_tools(enabled_only=False, check_module_active=False)
        available_tool_names = sorted([t.name for t in all_tools])

        try:
            limit = int(request.query.get("limit", 50))
            offset = int(request.query.get("offset", 0))
        except (ValueError, TypeError):
            limit = 50
            offset = 0

        logs = await auditor.list_recent_executions(
            tool_name=request.query.get("tool_name") or request.query.get("tool"),
            module_name=request.query.get("module"),
            status=request.query.get("status"),
            limit=limit,
            offset=offset,
        )

        return response.render_json({
            "success": True,
            "data": logs,
            "meta": {
                "limit": limit,
                "offset": offset,
                "count": len(logs),
                "available_tools": available_tool_names,
            }
        }, status_code=200)

    @classmethod
    async def me(cls, request: Request, response: Response):
        """GET /me - Informations sur le profil utilisateur connecté."""
        user_ctx = await cls._authenticate_request(request)
        if not user_ctx:
            err = AuthenticationRequiredError()
            return response.render_json(err.to_dict(), status_code=err.status_code)

        return response.render_json({
            "success": True,
            "data": {
                "user_id": user_ctx.get("user_id"),
                "username": user_ctx.get("username") or user_ctx.get("email") or user_ctx.get("user_id"),
                "is_sudo": bool(user_ctx.get("is_sudo", False)),
                "permissions": list(user_ctx.get("permissions", [])),
                "auth_type": user_ctx.get("auth_type", "session"),
            }
        }, status_code=200)

    @classmethod
    async def overview(cls, request: Request, response: Response):
        """GET /overview - Synthèse et KPIs globaux pour le tableau de bord SPA."""
        user_ctx = await cls._authenticate_request(request)
        if not user_ctx:
            err = AuthenticationRequiredError()
            return response.render_json(err.to_dict(), status_code=err.status_code)

        registry = ToolRegistry.get_instance(app=request.app)
        auditor = MCPAuditor(app=request.app)

        tools = registry.list_tools(enabled_only=False, check_module_active=False)
        active_tools = [t for t in tools if t.enabled and registry.is_module_active(t.module)]
        recent_logs = await auditor.list_recent_executions(limit=10)

        data = {
            "active_tools_count": len(active_tools),
            "total_tools_count": len(tools),
            "catalog_revision": registry.get_revision(),
            "contract_version": CONTRACT_VERSION,
            "recent_logs": recent_logs,
            "server_url": MCPApiKeyService(app=request.app).get_server_url(),
        }
        return response.render_json({"success": True, "data": data}, status_code=200)

    @classmethod
    async def server_status(cls, request: Request, response: Response):
        """GET /server/status - Ping direct et supervision temps réel du serveur MCP."""
        user_ctx = await cls._authenticate_request(request)
        if not user_ctx:
            err = AuthenticationRequiredError()
            return response.render_json(err.to_dict(), status_code=err.status_code)

        import time
        import httpx

        app = getattr(request, "app", None)
        registry = ToolRegistry.get_instance(app=app)
        api_key_service = MCPApiKeyService(app=app)

        mcp_server_url = api_key_service.get_server_url() or "http://localhost:8765/mcp"
        clean_url = mcp_server_url.rstrip("/")
        for suffix in ("/mcp", "/sse"):
            if clean_url.endswith(suffix):
                clean_url = clean_url[:-len(suffix)].rstrip("/")
                break
        server_base_url = clean_url or "http://localhost:8765"

        is_online = False
        latency_ms = 0.0
        server_status_val = "UNHEALTHY"
        server_tools_count = 0
        server_revision = None
        server_uptime = None
        server_version = "0.1.0"
        error_detail = None

        start_time = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=2.5) as client:
                health_resp = await client.get(f"{server_base_url}/health")
                elapsed = time.monotonic() - start_time
                latency_ms = round(elapsed * 1000, 1)

                if health_resp.status_code == 200:
                    is_online = True
                    hdata = health_resp.json()
                    server_status_val = hdata.get("status", "HEALTHY").upper()
                    server_tools_count = hdata.get("tools_count", 0)
                    server_revision = hdata.get("catalog_revision") or hdata.get("revision")
                    server_uptime = hdata.get("uptime") or "En ligne"
                    server_version = hdata.get("version", "0.1.0")
                else:
                    server_status_val = "DEGRADED"
                    error_detail = f"Code HTTP {health_resp.status_code}"
        except Exception as e:
            is_online = False
            server_status_val = "UNHEALTHY"
            error_detail = f"Impossible de joindre {server_base_url} : {e}"

        result = {
            "is_online": is_online,
            "latency_ms": latency_ms,
            "server_status": server_status_val,
            "server_tools_count": server_tools_count,
            "total_erp_tools": registry.count(enabled_only=True),
            "catalog_revision": registry.get_revision(),
            "server_revision": server_revision,
            "server_uptime": server_uptime or "-",
            "server_version": server_version,
            "error_detail": error_detail,
            "mcp_server_url": mcp_server_url,
            "server_base_url": server_base_url,
            "jwt_secret_set": bool(api_key_service.get_jwt_secret()),
            "mcp_api_key_set": bool(api_key_service.get_server_api_key()),
        }
        return response.render_json({"success": True, "data": result}, status_code=200)

    @classmethod
    async def server_sync(cls, request: Request, response: Response):
        """POST /server/sync - Déclenche la synchronisation forcée sur le serveur MCP."""
        user_ctx = await cls._authenticate_request(request)
        if not user_ctx:
            err = AuthenticationRequiredError()
            return response.render_json(err.to_dict(), status_code=err.status_code)

        import httpx
        app = getattr(request, "app", None)
        api_key_service = MCPApiKeyService(app=app)

        mcp_server_url = api_key_service.get_server_url() or "http://localhost:8765/mcp"
        clean_url = mcp_server_url.rstrip("/")
        for suffix in ("/mcp", "/sse"):
            if clean_url.endswith(suffix):
                clean_url = clean_url[:-len(suffix)].rstrip("/")
                break
        server_base_url = clean_url or "http://localhost:8765"

        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                internal_key = api_key_service.get_internal_key()
                headers = {
                    "Authorization": f"Bearer {internal_key}",
                    "X-Internal-MCP-Key": internal_key,
                }
                sync_resp = await client.post(f"{server_base_url}/api/mcp/sync", headers=headers)
                if sync_resp.status_code == 404:
                    sync_resp = await client.post(f"{server_base_url}/admin/api/sync", headers=headers)

                if sync_resp.status_code == 200:
                    sdata = sync_resp.json() if hasattr(sync_resp, "json") else {}
                    cnt = sdata.get("tools_count", "N/A")
                    return response.render_json({
                        "success": True,
                        "data": sdata,
                        "message": f"Synchronisation réussie ! {cnt} outils synchronisés sur le serveur MCP."
                    }, status_code=200)
                else:
                    return response.render_json({
                        "success": False,
                        "error": {
                            "code": "SERVER_SYNC_ERROR",
                            "message": f"Le serveur MCP a répondu avec le statut {sync_resp.status_code}."
                        }
                    }, status_code=502)
        except Exception as e:
            return response.render_json({
                "success": False,
                "error": {
                    "code": "SERVER_UNREACHABLE",
                    "message": f"Impossible de joindre le serveur MCP : {e}"
                }
            }, status_code=503)

    @classmethod
    async def get_server_config(cls, request: Request, response: Response):
        """GET /server/config - Récupère les paramètres de connexion et le manifeste technique."""
        user_ctx = await cls._authenticate_request(request)
        if not user_ctx:
            err = AuthenticationRequiredError()
            return response.render_json(err.to_dict(), status_code=err.status_code)

        app = getattr(request, "app", None)
        registry = ToolRegistry.get_instance(app=app)
        api_key_service = MCPApiKeyService(app=app)
        current_rev = registry.get_revision()

        internal_key = api_key_service.get_internal_key()
        jwt_secret = api_key_service.get_jwt_secret()
        mcp_server_url = api_key_service.get_server_url()
        mcp_server_api_key = api_key_service.get_server_api_key()

        host = getattr(request, "host", "") or "localhost:5000"
        scheme = getattr(request, "scheme", "http") or "http"
        internal_api_url = f"{scheme}://{host}/api/melodi_mcp"

        melodi_version = "1.0.0"
        if hasattr(app, "config") and hasattr(app.config, "VERSION") and isinstance(getattr(app.config, "VERSION"), str):
            melodi_version = getattr(app.config, "VERSION")

        manifest_data = {
            "contract_version": CONTRACT_VERSION,
            "melodi_version": melodi_version,
            "catalog_revision": current_rev,
            "tools_count": registry.count(enabled_only=True),
            "capabilities": {
                "tools_discovery": True,
                "tool_execution": True,
                "etag_support": True,
                "dynamic_reload": True,
            },
            "server_info": {
                "provider": "MELODI ERP melodi_mcp",
                "auth_modes": ["bearer_jwt", "service_key"],
                "internal_endpoint": "/api/melodi_mcp",
                "api_url": internal_api_url,
            }
        }

        data = {
            "contract_version": CONTRACT_VERSION,
            "catalog_revision": current_rev,
            "internal_key": internal_key,
            "internal_api_url": internal_api_url,
            "internal_endpoint": "/api/melodi_mcp",
            "jwt_secret": jwt_secret,
            "mcp_server_url": mcp_server_url,
            "mcp_server_api_key": mcp_server_api_key,
            "manifest_json": json.dumps(manifest_data, indent=2, ensure_ascii=False),
        }
        return response.render_json({"success": True, "data": data}, status_code=200)

    @classmethod
    async def update_server_config(cls, request: Request, response: Response):
        """POST /server/config - Met à jour les paramètres de liaison MCP."""
        user_ctx = await cls._authenticate_request(request)
        if not user_ctx or not user_ctx.get("is_sudo"):
            return response.render_json({
                "success": False,
                "error": {
                    "code": MCPErrorCode.PERMISSION_DENIED.value,
                    "message": "Seul un super-administrateur peut modifier la configuration serveur.",
                }
            }, status_code=403)

        body = {}
        if hasattr(request, "get_json") and callable(request.get_json):
            raw = request.get_json()
            if isinstance(raw, dict):
                body = raw
        elif isinstance(getattr(request, "json", None), dict):
            body = request.json

        app = getattr(request, "app", None)
        api_key_service = MCPApiKeyService(app=app)

        if "internal_key" in body and body["internal_key"] is not None:
            await api_key_service.update_internal_key(str(body["internal_key"]).strip())

        if "jwt_secret" in body and body["jwt_secret"] is not None:
            await api_key_service.update_jwt_secret(str(body["jwt_secret"]).strip())

        if "mcp_server_url" in body and body["mcp_server_url"] is not None:
            await api_key_service.update_server_url(str(body["mcp_server_url"]).strip())

        if "mcp_server_api_key" in body and body["mcp_server_api_key"] is not None:
            await api_key_service.update_server_api_key(str(body["mcp_server_api_key"]).strip())

        return response.render_json({
            "success": True,
            "message": "Configuration serveur mise à jour avec succès."
        }, status_code=200)

    @classmethod
    async def generate_server_key(cls, request: Request, response: Response):
        """POST /server/config/generate - Génère une clé cryptographique sécurisée."""
        user_ctx = await cls._authenticate_request(request)
        if not user_ctx or not user_ctx.get("is_sudo"):
            return response.render_json({
                "success": False,
                "error": {
                    "code": MCPErrorCode.PERMISSION_DENIED.value,
                    "message": "Accès réservé aux super-administrateurs.",
                }
            }, status_code=403)

        body = {}
        if hasattr(request, "get_json") and callable(request.get_json):
            raw = request.get_json()
            if isinstance(raw, dict):
                body = raw
        elif isinstance(getattr(request, "json", None), dict):
            body = request.json

        key_type = (body.get("type") or "internal_key").strip()
        app = getattr(request, "app", None)
        api_key_service = MCPApiKeyService(app=app)

        if key_type == "jwt_secret":
            import secrets
            generated = secrets.token_urlsafe(32)
        else:
            generated = api_key_service.generate_secret_token(prefix="mcp_internal_")

        return response.render_json({
            "success": True,
            "data": {"type": key_type, "generated_key": generated}
        }, status_code=200)

    @classmethod
    async def manage_tokens(cls, request: Request, response: Response):
        """GET /tokens (liste) ou POST /tokens (création d'un token personnel 7 jours par défaut)."""
        user_ctx = await cls._authenticate_request(request)
        if not user_ctx:
            err = AuthenticationRequiredError(
                message="Authentification utilisateur requise : token personnel MCP manquant, invalide ou expiré. Veuillez générer un token dans MELODI > Mes Tokens MCP."
            )
            return response.render_json(err.to_dict(), status_code=err.status_code)

        api_key_service = MCPApiKeyService(app=request.app)
        user_id = str(user_ctx.get("user_id") or "")
        is_sudo = bool(user_ctx.get("is_sudo", False))

        if request.method == "POST":
            body = {}
            if hasattr(request, "get_json") and callable(request.get_json):
                raw_body = request.get_json()
                if isinstance(raw_body, dict):
                    body = raw_body
            elif isinstance(getattr(request, "json", None), dict):
                body = request.json

            name = (body.get("name") or f"Token MCP ({user_ctx.get('username', user_id)})").strip()
            raw_hours = body.get("expires_in_hours")
            raw_days = body.get("expires_in_days")
            try:
                if raw_hours is not None:
                    expires_in_hours = int(raw_hours)
                elif raw_days is not None:
                    expires_in_hours = int(raw_days) * 24
                else:
                    expires_in_hours = 24
            except (ValueError, TypeError):
                expires_in_hours = 24

            expires_in_hours = max(1, min(72, expires_in_hours))

            key_obj, raw_key = await api_key_service.create_key(
                name=name,
                role="user",
                permissions="*",
                created_by=user_id,
                expires_in_hours=expires_in_hours,
            )
            if not key_obj:
                return response.render_json({
                    "success": False,
                    "error": {
                        "code": MCPErrorCode.EXECUTION_FAILED.value,
                        "message": "Impossible de générer le token MCP.",
                    }
                }, status_code=500)

            token_data = key_obj.to_dict(mask_key=True)
            token_data["token"] = raw_key
            return response.render_json({
                "success": True,
                "data": token_data,
            }, status_code=201)

        # GET /tokens : retourne les tokens de l'utilisateur connecté (ou tous si sudo avec ?all=true)
        show_all = is_sudo and str(request.query.get("all", "")).lower() in ("true", "1")
        tokens = await api_key_service.list_keys(user_id=None if show_all else user_id)
        return response.render_json({
            "success": True,
            "data": tokens,
            "meta": {"total": len(tokens)},
        }, status_code=200)

    @classmethod
    async def delete_token(cls, request: Request, response: Response):
        """DELETE /tokens/<token_id> - Révoque/supprime un token de l'utilisateur."""
        user_ctx = await cls._authenticate_request(request)
        if not user_ctx:
            err = AuthenticationRequiredError(
                message="Authentification utilisateur requise : token personnel MCP manquant, invalide ou expiré. Veuillez générer un token dans MELODI > Mes Tokens MCP."
            )
            return response.render_json(err.to_dict(), status_code=err.status_code)

        raw_id = request.params.get("token_id") or request.query.get("id")
        try:
            token_id = int(raw_id)
        except (ValueError, TypeError):
            return response.render_json({
                "success": False,
                "error": {"code": "INVALID_ARGUMENTS", "message": "Identifiant de token invalide."}
            }, status_code=400)

        api_key_service = MCPApiKeyService(app=request.app)
        user_id = str(user_ctx.get("user_id") or "")
        is_sudo = bool(user_ctx.get("is_sudo", False))

        # Vérification que le token appartient bien à l'utilisateur (sauf sudo)
        user_keys = await api_key_service.list_keys(user_id=None if is_sudo else user_id)
        if not any(int(k.get("id", -1)) == token_id for k in user_keys):
            return response.render_json({
                "success": False,
                "error": {"code": MCPErrorCode.PERMISSION_DENIED.value, "message": "Token introuvable ou accès refusé."}
            }, status_code=403)

        deleted = await api_key_service.delete_key(token_id)
        return response.render_json({
            "success": deleted,
            "data": {"id": token_id, "revoked": deleted},
        }, status_code=200 if deleted else 404)

    @classmethod
    async def toggle_token(cls, request: Request, response: Response):
        """POST /tokens/<token_id>/toggle - Active ou suspend un token personnel."""
        user_ctx = await cls._authenticate_request(request)
        if not user_ctx:
            err = AuthenticationRequiredError()
            return response.render_json(err.to_dict(), status_code=err.status_code)

        raw_id = request.params.get("token_id") or request.query.get("id")
        try:
            token_id = int(raw_id)
        except (ValueError, TypeError):
            return response.render_json({
                "success": False,
                "error": {"code": "INVALID_ARGUMENTS", "message": "Identifiant de token invalide."}
            }, status_code=400)

        api_key_service = MCPApiKeyService(app=request.app)
        user_id = str(user_ctx.get("user_id") or "")
        is_sudo = bool(user_ctx.get("is_sudo", False))

        user_keys = await api_key_service.list_keys(user_id=None if is_sudo else user_id)
        if not any(int(k.get("id", -1)) == token_id for k in user_keys):
            return response.render_json({
                "success": False,
                "error": {"code": MCPErrorCode.PERMISSION_DENIED.value, "message": "Token introuvable ou accès refusé."}
            }, status_code=403)

        res = await api_key_service.toggle_status(token_id)
        if not res:
            return response.render_json({
                "success": False,
                "error": {"code": "NOT_FOUND", "message": "Token introuvable."}
            }, status_code=404)

        return response.render_json({
            "success": True,
            "data": res,
            "message": f"Token {'activé' if res.get('is_active') else 'suspendu'} avec succès."
        }, status_code=200)

    @classmethod
    async def oauth_token(cls, request: Request, response: Response):
        """POST /api/melodi_mcp/oauth/token - Échange de code d'autorisation contre un JWT d'accès."""
        app = getattr(request, "app", None) or (getattr(request.module, "app", None) if hasattr(request, "module") else None)
        from ..services.oauth_service import MCPOAuthService
        oauth_service = MCPOAuthService.get_instance(app=app)
        api_key_service = MCPApiKeyService(app=app)

        data = {}
        if hasattr(request, "get_json") and callable(request.get_json):
            try:
                raw = request.get_json()
                if isinstance(raw, dict):
                    data = raw
            except Exception:
                pass
        if not data and hasattr(request, "form") and isinstance(request.form, dict):
            data = request.form
        if not data and hasattr(request, "query") and isinstance(request.query, dict):
            data = request.query

        grant_type = str(data.get("grant_type") or "").strip()
        if grant_type != "authorization_code":
            return response.render_json(
                {
                    "error": "unsupported_grant_type",
                    "error_description": "Seul le grant_type 'authorization_code' est supporté.",
                },
                status_code=400,
            )

        code = str(data.get("code") or "").strip()
        if not code:
            return response.render_json(
                {"error": "invalid_request", "error_description": "Le paramètre 'code' est obligatoire."},
                status_code=400,
            )

        client_id = str(data.get("client_id") or "ai_client").strip()
        redirect_uri = str(data.get("redirect_uri") or "").strip() or None
        code_verifier = str(data.get("code_verifier") or "").strip() or None

        auth_record = oauth_service.consume_authorization_code(
            code=code,
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_verifier=code_verifier,
        )

        if not auth_record:
            return response.render_json(
                {
                    "error": "invalid_grant",
                    "error_description": "Code d'autorisation invalide, expiré ou échec de la validation PKCE.",
                },
                status_code=400,
            )

        user_id = auth_record["user_id"]
        # Création et signature d'un token JWT officiel pour l'utilisateur
        key_obj, raw_token = await api_key_service.create_key(
            name=f"OAuth - {client_id}",
            role="user",
            permissions="*",
            created_by=user_id,
            expires_in_hours=24,
        )

        if not raw_token:
            return response.render_json(
                {"error": "server_error", "error_description": "Impossible de générer le jeton d'accès."},
                status_code=500,
            )

        token_id = getattr(key_obj, "key_prefix", None) or "mcp_token"

        return response.render_json(
            {
                "access_token": raw_token,
                "token_type": "Bearer",
                "expires_in": 86400,
                "scope": "mcp:all",
                "user_id": user_id,
                "token_id": token_id,
            },
            status_code=200,
        )
