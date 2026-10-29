import json
from core.page_builder import Page, Component
from core.routing import Request, Response
from base.components import admin_layout
from ..services.tool_registry import ToolRegistry
from ..services.auditor import MCPAuditor
from ..services.api_key_service import MCPApiKeyService
from ..config import CONTRACT_VERSION, MCP_INTERNAL_KEY


class MCPWebController:
    """Contrôleur Web d'administration pour melodi_mcp."""

    @staticmethod
    async def admin_dashboard(request: Request, response: Response):
        """Page principale d'administration et vue d'ensemble du catalogue MCP."""
        registry = ToolRegistry.get_instance(app=request.app)
        auditor = MCPAuditor(app=request.app)

        tools = registry.list_tools(enabled_only=False, check_module_active=False)
        active_tools = [t for t in tools if t.enabled and registry.is_module_active(t.module)]
        recent_logs = await auditor.list_recent_executions(limit=30)

        tools_data = []
        for t in tools:
            td = t.to_mcp_dict()
            td["is_active"] = t.enabled and registry.is_module_active(t.module)
            tools_data.append(td)

        content = Component(module_name="melodi_mcp", name="dashboard", context={
            "tools": tools_data,
            "active_tools_count": len(active_tools),
            "total_tools_count": len(tools),
            "catalog_revision": registry.get_revision(),
            "contract_version": CONTRACT_VERSION,
            "recent_logs": recent_logs,
        })

        page = Page("Catalogue MCP", admin_layout(content))
        return await response.render_page(page)

    @staticmethod
    async def admin_audit(request: Request, response: Response):
        """Page d'historique et d'audit des exécutions d'outils MCP."""
        registry = ToolRegistry.get_instance(app=request.app)
        auditor = MCPAuditor(app=request.app)

        filter_tool = request.query.get("tool")
        filter_status = request.query.get("status")

        logs = await auditor.list_recent_executions(
            tool_name=filter_tool,
            status=filter_status,
            limit=100
        )

        all_tools = registry.list_tools(enabled_only=False, check_module_active=False)
        available_tool_names = sorted([t.name for t in all_tools])

        content = Component(module_name="melodi_mcp", name="audit", context={
            "logs": logs,
            "available_tools": available_tool_names,
            "filter_tool": filter_tool or "",
            "filter_status": filter_status or "",
        })

        page = Page("Journal d'Audit MCP", admin_layout(content))
        return await response.render_page(page)

    @staticmethod
    async def admin_manifest(request: Request, response: Response):
        """Page d'état, manifeste et paramètres de connexion pour melodi_mcp_server."""
        app = getattr(request, "app", None) or (getattr(request.module, "app", None) if hasattr(request, "module") else None)
        registry = ToolRegistry.get_instance(app=app)
        api_key_service = MCPApiKeyService(app=app)
        current_rev = registry.get_revision()

        message = None
        message_type = None

        if request.method == "POST":
            form = request.form or {}
            action = form.get("action")
            if action in ("update_key", "update", None):
                new_key = (form.get("internal_key") or "").strip()
                if not new_key and form.get("generate") == "1":
                    new_key = api_key_service.generate_secret_token(prefix="mcp_internal_")
                if new_key:
                    await api_key_service.update_internal_key(new_key)
                    message = "Clé d'authentification interne mise à jour avec succès."
                    message_type = "success"
                else:
                    message = "Veuillez fournir une clé d'authentification valide ou générer une nouvelle valeur."
                    message_type = "danger"

        internal_key = api_key_service.get_internal_key()

        manifest_data = {
            "contract_version": CONTRACT_VERSION,
            "melodi_version": getattr(getattr(app, "config", None), "VERSION", "1.0.0"),
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
                "internal_endpoint": "/api/melodi_mcp/internal",
            }
        }

        content = Component(module_name="melodi_mcp", name="manifest", context={
            "contract_version": CONTRACT_VERSION,
            "catalog_revision": current_rev,
            "internal_key": internal_key,
            "manifest_json": json.dumps(manifest_data, indent=2, ensure_ascii=False),
            "message": message,
            "message_type": message_type,
        })

        page = Page("Serveur MCP & Manifeste", admin_layout(content))
        return await response.render_page(page)

    @staticmethod
    async def admin_api_keys(request: Request, response: Response):
        """Page de génération et de gestion des tokens MCP de l'utilisateur en cours (validité 7 jours par défaut)."""
        app = getattr(request, "app", None) or (getattr(request.module, "app", None) if hasattr(request, "module") else None)
        api_key_service = MCPApiKeyService(app=app)

        # Récupération de l'utilisateur actuellement connecté (data_context, request.get_session ou quart.session)
        user_payload = None
        if hasattr(request, "data_context") and isinstance(request.data_context, dict):
            user_payload = request.data_context.get("user_payload")

        if not user_payload and hasattr(request, "get_session") and callable(request.get_session):
            raw_session = request.get_session("user_payload")
            if isinstance(raw_session, (str, dict)):
                try:
                    user_payload = json.loads(raw_session) if isinstance(raw_session, str) else raw_session
                except Exception:
                    user_payload = None

        if not user_payload:
            try:
                from quart import session as quart_session
                raw_q = quart_session.get("user_payload")
                if isinstance(raw_q, (str, dict)):
                    user_payload = json.loads(raw_q) if isinstance(raw_q, str) else raw_q
            except Exception:
                user_payload = None

        user_id = "system"
        username = "Utilisateur"
        is_sudo = False
        user_permissions = []

        if isinstance(user_payload, dict) and user_payload.get("user_id"):
            user_id = str(user_payload["user_id"])
            username = str(user_payload.get("username") or user_payload.get("email") or user_id)
            is_sudo = bool(user_payload.get("is_sudo", False))
            if app and hasattr(app, "cache") and app.cache:
                perms_map = app.cache.get("user_permissions") or {}
                user_permissions = list(perms_map.get(user_id, []))
            elif isinstance(user_payload.get("permissions"), list):
                user_permissions = list(user_payload["permissions"])

        newly_created_key = None
        message = None
        message_type = None

        if request.method == "POST":
            form = request.form or {}
            action = form.get("action")

            if action == "create":
                name = (form.get("name") or "").strip() or f"Token MCP - {username}"
                try:
                    raw_exp = form.get("expires_in_days", 30)
                    expires_in_days = int(raw_exp) if raw_exp not in (None, "") else 30
                except (ValueError, TypeError):
                    expires_in_days = 30

                key_obj, raw_key = await api_key_service.create_key(
                    name=name,
                    role="user",
                    permissions="*",
                    created_by=user_id,
                    expires_in_days=expires_in_days,
                )
                if key_obj:
                    newly_created_key = raw_key
                    message = f"Token personnel '{name}' généré pour {username} (valable {expires_in_days} jours)."
                    message_type = "success"
                else:
                    message = "Erreur lors de la génération du token utilisateur."
                    message_type = "danger"

            elif action == "toggle":
                try:
                    key_id = int(form.get("key_id", 0))
                    res = await api_key_service.toggle_status(key_id)
                    if res:
                        state_str = "activé" if res["is_active"] else "révoqué"
                        message = f"Token {state_str} avec succès."
                        message_type = "info"
                except Exception as e:
                    message = f"Erreur de modification du statut: {e}"
                    message_type = "danger"

            elif action == "delete":
                try:
                    key_id = int(form.get("key_id", 0))
                    deleted = await api_key_service.delete_key(key_id)
                    if deleted:
                        message = "Token supprimé avec succès."
                        message_type = "warning"
                except Exception as e:
                    message = f"Erreur lors de la suppression: {e}"
                    message_type = "danger"

        # Liste uniquement les tokens de l'utilisateur en cours (ou tous si test unitaire sans session user)
        filter_user_id = user_id if user_id != "system" else None
        keys = await api_key_service.list_keys(user_id=filter_user_id)

        content = Component(module_name="melodi_mcp", name="api_keys", context={
            "keys": keys,
            "current_user_id": user_id,
            "current_username": username,
            "current_user_is_sudo": is_sudo,
            "current_user_permissions": user_permissions,
            "contract_version": CONTRACT_VERSION,
            "newly_created_key": newly_created_key,
            "message": message,
            "message_type": message_type,
        })

        page = Page("Mes Tokens MCP (Agent IA)", admin_layout(content))
        return await response.render_page(page)
