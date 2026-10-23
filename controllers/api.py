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


class MCPAPIController:
    """Contrôleur API REST interne pour melodi_mcp_server."""

    @classmethod
    def _authenticate_request(cls, request: Request) -> Optional[dict[str, Any]]:
        """Authentifie la requête entrante et extrait le contexte utilisateur vérifié."""
        # 1. Vérification session existante (web / admin)
        session_user = request.get_session("user_payload") if hasattr(request, "get_session") else None
        if session_user:
            user = json.loads(session_user) if isinstance(session_user, str) else session_user
            return user

        # 2. Vérification de l'en-tête Authorization
        auth_header = request.headers.get("Authorization", "")
        internal_key_header = request.headers.get("X-Internal-MCP-Key", "")

        token = None
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()

        # Mode A: Clé de service interne partagée
        if internal_key_header == MCP_INTERNAL_KEY or token == MCP_INTERNAL_KEY:
            # Vérifier si un contexte utilisateur signé est transmis en complément
            forwarded_user = request.headers.get("X-MCP-User-Token")
            if forwarded_user:
                decoded = JwtUtils.decode(forwarded_user)
                if decoded and "user_id" in decoded:
                    permissions_map = request.app.cache.get("user_permissions") or {} if hasattr(request.app, "cache") and request.app.cache else {}
                    perms = permissions_map.get(decoded["user_id"], [])
                    return {
                        "user_id": decoded["user_id"],
                        "username": decoded.get("username", "service_user"),
                        "is_sudo": decoded.get("is_sudo", False),
                        "permissions": perms,
                        "auth_type": "service_forwarded",
                    }

            # Identité de service autonome
            return {
                "user_id": "service_mcp",
                "username": "melodi_mcp_service",
                "is_sudo": True,
                "permissions": ["*"],
                "auth_type": "service_key",
            }

        # Mode B: Bearer Token JWT utilisateur standard
        if token:
            payload = JwtUtils.decode(token)
            if payload and "user_id" in payload:
                user_id = payload["user_id"]
                permissions_map = request.app.cache.get("user_permissions") or {} if hasattr(request.app, "cache") and request.app.cache else {}
                user_perms = permissions_map.get(user_id, [])
                return {
                    "user_id": user_id,
                    "username": payload.get("username", ""),
                    "is_sudo": payload.get("is_sudo", False),
                    "permissions": user_perms,
                    "auth_type": "jwt",
                }

        return None

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
        user_ctx = cls._authenticate_request(request)
        if not user_ctx:
            err = AuthenticationRequiredError()
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
        user_ctx = cls._authenticate_request(request)
        if not user_ctx:
            err = AuthenticationRequiredError()
            return response.render_json(err.to_dict(), status_code=err.status_code)

        # 2. Résolution du nom d'outil (paramètre d'URL, query string, ou body)
        tool_name = (
            request.params.get("tool_name")
            or request.params.get("name")
            or request.query.get("tool_name")
            or request.json.get("tool_name")
            or request.json.get("name")
        )

        if not tool_name:
            return response.render_json({
                "success": False,
                "error": {
                    "code": MCPErrorCode.TOOL_NOT_FOUND.value,
                    "message": "Le nom de l'outil à exécuter est requis.",
                }
            }, status_code=400)

        body = request.json or {}
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
        """GET /internal/audit-logs - Historique d'audit des exécutions."""
        user_ctx = cls._authenticate_request(request)
        if not user_ctx:
            err = AuthenticationRequiredError()
            return response.render_json(err.to_dict(), status_code=err.status_code)

        auditor = MCPAuditor(app=request.app)
        try:
            limit = int(request.query.get("limit", 50))
            offset = int(request.query.get("offset", 0))
        except (ValueError, TypeError):
            limit = 50
            offset = 0

        logs = await auditor.list_recent_executions(
            tool_name=request.query.get("tool_name"),
            module_name=request.query.get("module"),
            status=request.query.get("status"),
            limit=limit,
            offset=offset,
        )

        return response.render_json({
            "success": True,
            "data": logs,
            "meta": {"limit": limit, "offset": offset, "count": len(logs)}
        }, status_code=200)
