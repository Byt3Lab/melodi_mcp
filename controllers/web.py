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
        registry = ToolRegistry.get_instance(app=request.app)
        current_rev = registry.get_revision()

        manifest_data = {
            "contract_version": CONTRACT_VERSION,
            "melodi_version": getattr(getattr(request.app, "config", None), "VERSION", "1.0.0"),
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
            "internal_key": MCP_INTERNAL_KEY,
            "manifest_json": json.dumps(manifest_data, indent=2, ensure_ascii=False),
        })

        page = Page("Serveur MCP & Manifeste", admin_layout(content))
        return await response.render_page(page)

    @staticmethod
    async def admin_api_keys(request: Request, response: Response):
        """Page de gestion et de génération des clés d'API MCP."""
        app = getattr(request, "app", None) or (getattr(request.module, "app", None) if hasattr(request, "module") else None)
        api_key_service = MCPApiKeyService(app=app)

        newly_created_key = None
        message = None
        message_type = None

        if request.method == "POST":
            form = request.form or {}
            action = form.get("action")

            if action == "create":
                name = (form.get("name") or "").strip() or "Clé MCP"
                role = (form.get("role") or "service").strip()
                permissions = (form.get("permissions") or "*").strip()
                custom_key = (form.get("custom_key") or "").strip() or None
                key_obj, raw_key = await api_key_service.create_key(
                    name=name,
                    role=role,
                    permissions=permissions,
                    custom_key=custom_key,
                )
                if key_obj:
                    newly_created_key = raw_key
                    message = f"Clé '{name}' créée avec succès."
                    message_type = "success"
                else:
                    message = "Erreur lors de la création de la clé d'API."
                    message_type = "danger"

            elif action == "toggle":
                try:
                    key_id = int(form.get("key_id", 0))
                    res = await api_key_service.toggle_status(key_id)
                    if res:
                        state_str = "activée" if res["is_active"] else "désactivée"
                        message = f"Clé {state_str} avec succès."
                        message_type = "info"
                except Exception as e:
                    message = f"Erreur de modification du statut: {e}"
                    message_type = "danger"

            elif action == "delete":
                try:
                    key_id = int(form.get("key_id", 0))
                    deleted = await api_key_service.delete_key(key_id)
                    if deleted:
                        message = "Clé d'API supprimée avec succès."
                        message_type = "warning"
                except Exception as e:
                    message = f"Erreur lors de la suppression: {e}"
                    message_type = "danger"

        # Liste des clés
        keys = await api_key_service.list_keys()

        content = Component(module_name="melodi_mcp", name="api_keys", context={
            "keys": keys,
            "contract_version": CONTRACT_VERSION,
            "default_internal_key": MCP_INTERNAL_KEY,
            "newly_created_key": newly_created_key,
            "message": message,
            "message_type": message_type,
        })

        page = Page("Gestion des Clés d'API MCP", admin_layout(content))
        return await response.render_page(page)
