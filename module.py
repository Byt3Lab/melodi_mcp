from __future__ import annotations
import inspect
from typing import Any, Callable

from core.module import ApplicationModule, Permission
from .config import MODULE_NAME
from .controllers.api import MCPAPIController
from .controllers.web import MCPWebController
from .services.executor import ToolExecutor
from .services.tool_registry import ToolRegistry


class MelodiMCPModule(ApplicationModule):
    """Module MELODI MCP - Fournisseur interne d'outils et de capacités pour assistants IA."""

    def __init__(self, name: str, router_name: str):
        super().__init__(name=name, router_name=router_name)
        self.registry: ToolRegistry | None = None
        self.executor: ToolExecutor | None = None

    def _get_permissions(self) -> list[Permission]:
        return [
            Permission(self, "mcp:read", "Consulter le catalogue des outils et l'historique d'audit MCP"),
            Permission(self, "mcp:execute", "Exécuter des outils via l'interface interne MCP"),
            Permission(self, "mcp:admin", "Administration complète et configuration du module MCP"),
        ]

    async def run_dev_migrations(self):
        """Création automatique des tables de stockage du module melodi_mcp."""
        from .models.models import MCPAuditLogModel
        if self.app and hasattr(self.app, "db") and self.app.db:
            try:
                await self.app.db.create_all([MCPAuditLogModel])
            except Exception as e:
                print(f"[melodi_mcp] Erreur lors des migrations dev: {e}")

    def _register_routes(self):
        """Enregistre les routes Web d'administration et les routes API REST."""
        # 1. Routes d'administration Web
        self.admin_router.add_route("", MCPWebController.admin_dashboard, methods=["GET"])
        self.admin_router.add_route("/", MCPWebController.admin_dashboard, methods=["GET"])

        # 2. Routes API REST internes destinées à melodi_mcp_server
        # Endpoints de santé et manifeste
        self.api_router.add_route("/health", MCPAPIController.health, methods=["GET"])
        self.api_router.add_route("/internal/health", MCPAPIController.health, methods=["GET"])
        self.api_router.add_route("/manifest", MCPAPIController.manifest, methods=["GET"])
        self.api_router.add_route("/internal/manifest", MCPAPIController.manifest, methods=["GET"])

        # Révision rapide du catalogue (avec support ETag / 304 Not Modified)
        self.api_router.add_route("/revision", MCPAPIController.get_revision, methods=["GET"])
        self.api_router.add_route("/internal/revision", MCPAPIController.get_revision, methods=["GET"])

        # Découverte du catalogue d'outils
        self.api_router.add_route("/tools", MCPAPIController.list_tools, methods=["GET"])
        self.api_router.add_route("/internal/tools", MCPAPIController.list_tools, methods=["GET"])

        # Exécution d'un outil (chemins dynamiques et chemin fixe pour query/body)
        self.api_router.add_route("/tools/<tool_name>/execute", MCPAPIController.execute_tool, methods=["POST"])
        self.api_router.add_route("/internal/tools/<tool_name>/execute", MCPAPIController.execute_tool, methods=["POST"])
        self.api_router.add_route("/tools/execute", MCPAPIController.execute_tool, methods=["POST"])
        self.api_router.add_route("/internal/tools/execute", MCPAPIController.execute_tool, methods=["POST"])

        # Journaux d'audit
        self.api_router.add_route("/internal/audit-logs", MCPAPIController.audit_logs, methods=["GET"])
        self.api_router.add_route("/audit-logs", MCPAPIController.audit_logs, methods=["GET"])

    def _register_actions(self):
        """Enregistre les actions exposées aux autres modules MELODI."""
        self.add_action("register_tool", self.action_register_tool)
        self.add_action("register_tools", self.action_register_tools)
        self.add_action("unregister_tool", self.action_unregister_tool)
        self.add_action("unregister_module_tools", self.action_unregister_module_tools)
        self.add_action("get_catalog", self.action_get_catalog)
        self.add_action("execute_tool", self.action_execute_tool)

    def _register_navigation(self):
        """Enregistre le module dans la barre de navigation du panneau d'administration."""
        self.register_navigation(
            id="mcp_root",
            label="Outils MCP",
            icon="name=smart_toy&fill=white",
            url="/admin/melodi_mcp",
            priority=45,
            required_role="mcp:read"
        )

    async def _collect_registry_contributions(self):
        """Scanne la zone 'mcp_tools' du Registry central MELODI pour enregistrer les outils déclarés."""
        if hasattr(self.app, "registry") and self.app.registry:
            zone_tools = self.app.registry.zones.get("mcp_tools", {})
            for mod_name, items in zone_tools.items():
                for item in items:
                    try:
                        if callable(item):
                            resolved = await item() if inspect.iscoroutinefunction(item) else item()
                            if isinstance(resolved, list):
                                for r in resolved:
                                    self._register_single_item(mod_name, r)
                            elif isinstance(resolved, dict):
                                self._register_single_item(mod_name, resolved)
                        elif isinstance(item, dict):
                            self._register_single_item(mod_name, item)
                    except Exception as e:
                        print(f"[melodi_mcp] Erreur lors de l'enregistrement de l'outil depuis le Registry ({mod_name}): {e}")

    def _register_single_item(self, module_name: str, item_dict: dict[str, Any]):
        if not item_dict.get("module"):
            item_dict["module"] = module_name
        self.registry.register_dict(item_dict)

    async def load(self):
        """Initialisation et démarrage du module MELODI MCP."""
        self.permissions = self._get_permissions()

        # Initialisation du registre
        self.registry = ToolRegistry.get_instance(app=self.app)
        self.executor = ToolExecutor(registry=self.registry, app=self.app)

        # Ajout de la zone de contribution mcp_tools dans le Registry MELODI
        self.add_registry_zone("mcp_tools")

        # Migrations dev si debug activé
        if self.app and hasattr(self.app, "server") and self.app.server and getattr(self.app.server.app, "debug", False):
            await self.run_dev_migrations()

        # Enregistrement des composants du module
        self._register_actions()
        self._register_routes()
        self._register_navigation()

        # Collecte initiale des outils enregistrés dans le Registry central
        await self._collect_registry_contributions()

        # Notification de disponibilité
        if hasattr(self, "notify_event_listener"):
            await self.notify_event_listener("mcp.catalog.ready", {
                "revision": self.registry.get_revision(),
                "tools_count": self.registry.count(),
            })

    def stop(self):
        """Arrêt du module."""
        print("[melodi_mcp] Arrêt du module.")

    # --- Handlers d'actions inter-modules ---

    async def action_register_tool(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Action inter-module permettant à un module métier d'enregistrer un outil."""
        try:
            tool = self.registry.register_dict(payload)
            return {
                "status": "success",
                "tool": tool.to_mcp_dict(),
                "catalog_revision": self.registry.get_revision(),
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def action_register_tools(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Action permettant d'enregistrer une liste d'outils en un seul appel."""
        tools_list = payload.get("tools", [])
        registered = []
        errors = []

        for item in tools_list:
            try:
                tool = self.registry.register_dict(item)
                registered.append(tool.name)
            except Exception as e:
                errors.append({"item": item.get("name", "unknown"), "error": str(e)})

        return {
            "status": "success" if not errors else "partial",
            "registered": registered,
            "errors": errors,
            "catalog_revision": self.registry.get_revision(),
        }

    async def action_unregister_tool(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Désenregistre un outil par son nom."""
        tool_name = payload.get("tool_name") or payload.get("name")
        success = self.registry.unregister(tool_name)
        return {
            "status": "success" if success else "error",
            "message": f"Outil '{tool_name}' supprimé" if success else f"Outil '{tool_name}' introuvable",
            "catalog_revision": self.registry.get_revision(),
        }

    async def action_unregister_module_tools(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Supprime tous les outils d'un module."""
        module_name = payload.get("module_name") or payload.get("module")
        count = self.registry.unregister_module(module_name)
        return {
            "status": "success",
            "removed_count": count,
            "catalog_revision": self.registry.get_revision(),
        }

    async def action_get_catalog(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Retourne le catalogue actif d'outils."""
        tools = self.registry.list_tools(
            module=payload.get("module"),
            category=payload.get("category"),
            read_only=payload.get("read_only"),
            enabled_only=payload.get("enabled_only", True),
        )
        return {
            "status": "success",
            "catalog_revision": self.registry.get_revision(),
            "tools": [t.to_mcp_dict() for t in tools],
        }

    async def action_execute_tool(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Exécute un outil programmatiquement."""
        tool_name = payload.get("tool_name")
        arguments = payload.get("arguments", {})
        user_context = payload.get("user_context", {"is_sudo": True, "user_id": "system"})
        correlation_id = payload.get("correlation_id")
        confirmed = payload.get("confirmed", False)
        business_context = payload.get("business_context", {})

        return await self.executor.execute(
            tool_name=tool_name,
            arguments=arguments,
            user_context=user_context,
            correlation_id=correlation_id,
            confirmed=confirmed,
            business_context=business_context,
        )


module = MelodiMCPModule(
    name=MODULE_NAME,
    router_name=MODULE_NAME,
)
