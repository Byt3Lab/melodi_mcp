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
        """GET /internal/audit-logs - Historique d'audit des exécutions."""
        user_ctx = await cls._authenticate_request(request)
        if not user_ctx:
            err = AuthenticationRequiredError(
                message="Authentification utilisateur requise : token personnel MCP manquant, invalide ou expiré. Veuillez générer un token dans MELODI > Mes Tokens MCP."
            )
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
