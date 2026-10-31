import json
import inspect
from typing import Any, Optional

from core.routing import Request, Response
from core.utils.jwt import JwtUtils
from .config import MCP_INTERNAL_KEY
from .contract.errors import AuthenticationRequiredError, PermissionDeniedError
from .services.api_key_service import MCPApiKeyService
from .services.tool_registry import ToolRegistry
from .services.executor import ToolExecutor

PUBLIC_MCP_PATHS = {
    "/health",
    "/internal/health",
    "/manifest",
    "/internal/manifest",
    "/revision",
    "/internal/revision",
}


async def resolve_mcp_user(request: Request, service_cls=None) -> Optional[dict[str, Any]]:
    """Valide le token du serveur MCP (X-Internal-MCP-Key) et le token de l'utilisateur (X-User-MCP-Key)."""
    # Si déjà résolu par le middleware dans data_context
    if hasattr(request, "data_context") and isinstance(request.data_context, dict):
        existing = request.data_context.get("user_payload")
        if existing:
            return existing

    app = getattr(request, "app", None) or (getattr(request.module, "app", None) if hasattr(request, "module") else None)

    # 1. Vérification session existante (web / admin)
    session_user = request.get_session("user_payload") if hasattr(request, "get_session") else None
    if session_user:
        user = json.loads(session_user) if isinstance(session_user, str) else session_user
        if isinstance(user, dict) and user.get("user_id"):
            if "permissions" not in user and app and hasattr(app, "cache") and app.cache:
                permissions_map = app.cache.get("user_permissions") or {}
                user["permissions"] = list(permissions_map.get(user["user_id"], []))
            return user

    # 2. Extraction des en-têtes d'authentification
    headers = getattr(request, "headers", None)
    if headers is None or not hasattr(headers, "get"):
        headers = {}

    def _get_header(name: str) -> str:
        if not hasattr(headers, "get"):
            return ""
        val = headers.get(name)
        if val is None or not isinstance(val, str):
            val = headers.get(name.lower())
        return val.strip() if isinstance(val, str) else ""

    auth_header = _get_header("Authorization")
    internal_key_header = _get_header("X-Internal-MCP-Key")
    melodi_user_id_header = (
        _get_header("X-Melodi-User-ID")
        or _get_header("X-Melodi-User-Id")
        or _get_header("X-Melodi-User")
    )

    query = getattr(request, "query", None)
    if query is None or not hasattr(query, "get"):
        query = {}

    def _get_query(name: str) -> str:
        if not hasattr(query, "get"):
            return ""
        val = query.get(name)
        return val.strip() if isinstance(val, str) else ""

    user_key_header = (
        _get_header("X-User-MCP-Key")
        or _get_header("X-MCP-User-Key")
        or _get_header("X-MCP-User-Token")
        or _get_query("user_key")
        or _get_query("user_token")
    )

    token = None
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()

    svc_cls = service_cls or MCPApiKeyService
    api_key_service = svc_cls(app=app)
    try:
        current_internal_key = getattr(api_key_service, "get_internal_key", lambda: MCP_INTERNAL_KEY)()
        if inspect.iscoroutine(current_internal_key):
            current_internal_key = await current_internal_key
        if not isinstance(current_internal_key, str):
            current_internal_key = MCP_INTERNAL_KEY
    except Exception:
        current_internal_key = MCP_INTERNAL_KEY

    internal_keys = {MCP_INTERNAL_KEY}
    if isinstance(current_internal_key, str) and current_internal_key:
        internal_keys.add(current_internal_key)

    # Vérification de l'authentification serveur MCP (X-Internal-MCP-Key ou Bearer token de service)
    is_server_call = False
    if internal_key_header and internal_key_header in internal_keys:
        is_server_call = True
    elif token and token in internal_keys:
        is_server_call = True

    # Si c'est un appel de service MCP avec identification directe de l'utilisateur (X-Melodi-User-ID)
    if is_server_call and melodi_user_id_header:
        user_id = melodi_user_id_header.strip()
        user = None
        if app and hasattr(app, "module_manager") and app.module_manager:
            try:
                from base.repositories.user_repository import UserRepository
                base_mod = app.module_manager.get_module("base") if hasattr(app.module_manager, "get_module") else None
                if not base_mod and hasattr(app.module_manager, "modules"):
                    base_mod = app.module_manager.modules.get("base")
                if base_mod:
                    user = await UserRepository(base_mod).get_user_by_id(user_id)
                    if user is not None and not getattr(user, "is_active", True):
                        return None
            except Exception:
                pass

        permissions_map = app.cache.get("user_permissions") or {} if app and hasattr(app, "cache") and app.cache else {}
        user_perms = list(permissions_map.get(user_id, []))
        branches_map = app.cache.get("user_branches") or {} if app and hasattr(app, "cache") and app.cache else {}
        user_branches = branches_map.get(user_id, [])
        active_branch = user_branches[0] if user_branches else None
        is_sudo = bool(getattr(user, "is_sudo", False)) if user else False
        username = getattr(user, "username", None) or user_id

        return {
            "user_id": user_id,
            "username": username,
            "is_sudo": is_sudo,
            "permissions": user_perms,
            "active_branch": active_branch,
            "auth_type": "jwt_user",
            "server_authenticated": True,
        }

    # Clé / Token utilisateur candidat
    candidate_user_key = user_key_header.strip() if isinstance(user_key_header, str) and user_key_header.strip() else ""
    if not candidate_user_key and token and token not in internal_keys:
        candidate_user_key = token
    if not candidate_user_key and internal_key_header and not is_server_call:
        candidate_user_key = internal_key_header

    # Si un token utilisateur (X-User-MCP-Key ou Bearer) est fourni :
    if candidate_user_key and isinstance(candidate_user_key, str) and candidate_user_key.strip():
        # A. Vérification comme token MCP utilisateur (JWT ou clé en base)
        try:
            verified = await api_key_service.verify_key(candidate_user_key)
            if verified:
                if is_server_call:
                    verified["server_authenticated"] = True
                return verified
        except Exception as e:
            print(f"[melodi_mcp] Erreur lors de la vérification du token utilisateur: {e}")

        # B. Vérification comme token JWT utilisateur MELODI standard
        payload = JwtUtils.decode(candidate_user_key)
        if payload and "user_id" in payload:
            user_id = payload["user_id"]
            is_sudo = payload.get("is_sudo", False)
            username = payload.get("username", "")

            if app and hasattr(app, "module_manager") and app.module_manager:
                try:
                    from base.repositories.user_repository import UserRepository
                    base_mod = app.module_manager.get_module("base") if hasattr(app.module_manager, "get_module") else None
                    if not base_mod and hasattr(app.module_manager, "modules"):
                        base_mod = app.module_manager.modules.get("base")
                    if base_mod:
                        user_obj = await UserRepository(base_mod).get_user_by_id(user_id)
                        if user_obj is not None:
                            if not getattr(user_obj, "is_active", True):
                                return None
                            is_sudo = bool(getattr(user_obj, "is_sudo", is_sudo))
                            username = getattr(user_obj, "username", username)
                except Exception:
                    pass

            permissions_map = app.cache.get("user_permissions") or {} if app and hasattr(app, "cache") and app.cache else {}
            user_perms = list(permissions_map.get(user_id, []))
            return {
                "user_id": user_id,
                "username": username,
                "is_sudo": is_sudo,
                "permissions": user_perms,
                "auth_type": "jwt",
                "server_authenticated": is_server_call,
            }

        # Token utilisateur fourni mais invalide
        return None

    # Si seul le serveur MCP est authentifié via X-Internal-MCP-Key (sans token utilisateur X-User-MCP-Key) :
    if is_server_call:
        raw_path = getattr(request, "path", "") or ""
        path = str(raw_path) if isinstance(raw_path, str) else ""
        # Pour exécuter un outil (/execute), le token utilisateur de l'agent est exigé pour contrôler les permissions !
        if path.endswith("/execute"):
            return None

        # Pour les opérations système / découverte de catalogue
        return {
            "user_id": "service_mcp",
            "username": "melodi_mcp_service",
            "is_sudo": True,
            "permissions": ["*"],
            "auth_type": "service_key",
            "server_authenticated": True,
        }

    return None


def _extract_tool_name_from_request(request: Request, rel_path: str) -> Optional[str]:
    """Extrait le nom de l'outil ciblé par la requête (URL, query ou JSON body)."""
    params = getattr(request, "params", {}) or {}
    query = getattr(request, "query", {}) or {}

    tool_name = params.get("tool_name") or params.get("name") or query.get("tool_name")
    if tool_name:
        return str(tool_name).strip()

    # Extraction depuis l'URL type /tools/<tool_name>/execute ou /internal/tools/<tool_name>/execute
    parts = [p for p in rel_path.strip("/").split("/") if p]
    if len(parts) >= 3 and parts[-1] == "execute" and parts[-3] == "tools":
        candidate = parts[-2]
        if candidate != "execute":
            return candidate

    # Extraction depuis le corps JSON
    body = {}
    if hasattr(request, "get_json") and callable(request.get_json):
        try:
            raw_body = request.get_json()
            if isinstance(raw_body, dict):
                body = raw_body
        except Exception:
            body = {}
    elif isinstance(getattr(request, "json", None), dict):
        body = request.json

    if isinstance(body, dict):
        from_body = body.get("tool_name") or body.get("name")
        if from_body:
            return str(from_body).strip()

    return None


async def mcp_auth_middleware(request: Request, response: Response):
    """Middleware melodi_mcp :
    1. Valide le token de l'utilisateur et identifie l'utilisateur MELODI.
    2. Récupère les permissions enregistrées sur le tool demandé et vérifie via le système
       de permissions MELODI (check_user_permission) que l'utilisateur est autorisé à continuer.
    """
    path = getattr(request, "path", "") or ""
    # Normaliser le chemin relatif au routeur melodi_mcp
    rel_path = path
    for prefix in ("/api/melodi_mcp", "/melodi_mcp"):
        if rel_path.startswith(prefix):
            rel_path = rel_path[len(prefix):] or "/"
            break

    user_ctx = await resolve_mcp_user(request)
    if not user_ctx:
        if rel_path in PUBLIC_MCP_PATHS:
            return None
        err = AuthenticationRequiredError()
        return response.render_json(err.to_dict(), status_code=err.status_code)

    if not hasattr(request, "data_context") or not isinstance(request.data_context, dict):
        request.data_context = {}
    request.data_context["user_payload"] = user_ctx

    # Si la requête concerne l'exécution d'un tool, le middleware récupère les permissions
    # déclarées lors de l'enregistrement du tool et demande au système MELODI si l'utilisateur
    # identifié possède ces permissions pour continuer.
    if rel_path.endswith("/execute"):
        app = getattr(request, "app", None) or (getattr(request.module, "app", None) if hasattr(request, "module") else None)
        tool_name = _extract_tool_name_from_request(request, rel_path)
        if tool_name:
            registry = ToolRegistry.get_instance(app=app)
            tool = registry.get(tool_name)
            if tool is not None:
                request.data_context["mcp_tool"] = tool
                executor = ToolExecutor(registry=registry, app=app)
                try:
                    executor._verify_permissions(tool, user_ctx)
                except PermissionDeniedError as perm_err:
                    return response.render_json(perm_err.to_dict(), status_code=perm_err.status_code)

    return None
