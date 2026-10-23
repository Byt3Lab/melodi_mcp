from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Optional, Union

from ..contract.tool_definition import ToolDefinition


class ToolRegistry:
    """Registre central des outils MCP déclarés dans MELODI ERP.

    Assure la validation, la déduplication, le versionnage et le calcul
    de la révision du catalogue.
    """

    _instance: Optional[ToolRegistry] = None

    def __init__(self, app=None):
        self.app = app
        self._tools: dict[str, ToolDefinition] = {}
        self._revision: str = "initial"
        self._updated_at: datetime = datetime.now(timezone.utc)
        self._recompute_revision()

    @classmethod
    def get_instance(cls, app=None) -> ToolRegistry:
        if cls._instance is None:
            cls._instance = cls(app=app)
        elif app is not None and cls._instance.app is None:
            cls._instance.app = app
        return cls._instance

    @classmethod
    def reset_instance(cls):
        """Réinitialise l'instance singleton (utile pour les tests)."""
        cls._instance = None

    def register(self, tool: ToolDefinition) -> None:
        """Enregistre un outil dans le catalogue. Rejette les doublons et les déclarations invalides."""
        tool.validate()

        if tool.name in self._tools:
            existing = self._tools[tool.name]
            # Si même nom avec un module différent ou conflit
            if existing.module != tool.module:
                raise ValueError(
                    f"Conflit de nom d'outil : l'outil '{tool.name}' est déjà enregistré par le module '{existing.module}'. "
                    f"Le module '{tool.module}' ne peut pas utiliser le même nom."
                )

        self._tools[tool.name] = tool
        self._recompute_revision()
        self._notify_catalog_updated()

    def register_dict(self, data: dict[str, Any]) -> ToolDefinition:
        """Enregistre un outil défini sous forme de dictionnaire."""
        tool = ToolDefinition.from_dict(data)
        self.register(tool)
        return tool

    def unregister(self, name: str) -> bool:
        """Supprime un outil du registre."""
        if name in self._tools:
            del self._tools[name]
            self._recompute_revision()
            self._notify_catalog_updated()
            return True
        return False

    def unregister_module(self, module_name: str) -> int:
        """Supprime tous les outils appartenant à un module donné."""
        to_delete = [name for name, t in self._tools.items() if t.module == module_name]
        for name in to_delete:
            del self._tools[name]

        if to_delete:
            self._recompute_revision()
            self._notify_catalog_updated()

        return len(to_delete)

    def get(self, name: str) -> Optional[ToolDefinition]:
        """Récupère un outil par son nom."""
        return self._tools.get(name)

    def is_module_active(self, module_name: str) -> bool:
        """Vérifie si le module propriétaire est actif dans MELODI."""
        if not self.app or not hasattr(self.app, "module_manager"):
            return True
        mm = self.app.module_manager
        if hasattr(mm, "isOn"):
            return mm.isOn(module_name)
        return True

    def list_tools(
        self,
        module: Optional[str] = None,
        category: Optional[str] = None,
        enabled_only: bool = True,
        read_only: Optional[bool] = None,
        check_module_active: bool = True,
    ) -> list[ToolDefinition]:
        """Liste les outils du catalogue selon les filtres fournis."""
        result = []
        for tool in self._tools.values():
            if enabled_only and not tool.enabled:
                continue

            if check_module_active and not self.is_module_active(tool.module):
                continue

            if module and tool.module != module:
                continue

            if category and tool.category != category:
                continue

            if read_only is not None and tool.read_only != read_only:
                continue

            result.append(tool)

        return sorted(result, key=lambda t: t.name)

    def get_revision(self) -> str:
        """Retourne le hash de révision actuel du catalogue."""
        return self._revision

    def get_updated_at(self) -> datetime:
        return self._updated_at

    def count(self, enabled_only: bool = True) -> int:
        return len(self.list_tools(enabled_only=enabled_only))

    def _recompute_revision(self) -> None:
        """Calcule un hash SHA-256 déterministe représentant l'état canonique du catalogue."""
        active_tools = sorted(self._tools.values(), key=lambda t: t.name)
        payload = [
            {
                "name": t.name,
                "version": t.version,
                "module": t.module,
                "enabled": t.enabled,
                "input_schema": t.input_schema,
                "read_only": t.read_only,
                "destructive": t.destructive,
            }
            for t in active_tools
        ]
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        self._revision = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]
        self._updated_at = datetime.now(timezone.utc)

    def _notify_catalog_updated(self) -> None:
        """Émet un événement système lorsque le catalogue change."""
        if self.app and hasattr(self.app, "hook_manager") and self.app.hook_manager:
            try:
                ev_listener = getattr(self.app.hook_manager, "event_listener", None)
                if ev_listener and hasattr(ev_listener, "notify"):
                    import asyncio
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(
                            ev_listener.notify(
                                "melodi_mcp",
                                "mcp.catalog.updated",
                                {
                                    "revision": self._revision,
                                    "tools_count": len(self._tools),
                                    "timestamp": self._updated_at.isoformat(),
                                }
                            )
                        )
                    except RuntimeError:
                        pass
            except Exception as e:
                print(f"[melodi_mcp] Erreur émission mcp.catalog.updated: {e}")
