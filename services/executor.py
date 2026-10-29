import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Optional

from ..contract.errors import (
    BusinessError,
    ConfirmationRequiredError,
    ExecutionTimeoutError,
    InvalidArgumentsError,
    MCPErrorCode,
    MCPException,
    ModuleUnavailableError,
    PermissionDeniedError,
    ToolDisabledError,
    ToolNotFoundError,
)
from ..contract.tool_definition import ToolDefinition
from .auditor import MCPAuditor
from .tool_registry import ToolRegistry
from .validator import ArgumentValidator


class ToolExecutor:
    """Moteur d'exécution sécurisé et contrôlé des outils MCP."""

    def __init__(self, registry: ToolRegistry, app=None):
        self.registry = registry
        self.app = app
        self.auditor = MCPAuditor(app=app)

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        user_context: dict[str, Any],
        correlation_id: Optional[str] = None,
        confirmed: bool = False,
        business_context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Exécute un outil de manière strictement contrôlée et sécurisée."""
        start_time = time.monotonic()
        business_context = business_context or {}
        user_id = user_context.get("user_id")
        branch_id = business_context.get("branch_id") or user_context.get("active_branch")
        tool: Optional[ToolDefinition] = None

        try:
            # 1. Résolution de l'outil
            tool = self.registry.get(tool_name)
            if not tool:
                raise ToolNotFoundError(tool_name)

            if not tool.enabled:
                raise ToolDisabledError(tool_name)

            # 2. Vérification de l'activation du module propriétaire
            if not self.registry.is_module_active(tool.module):
                raise ModuleUnavailableError(tool.module)

            # 3. Contrôle d'accès RBAC
            self._verify_permissions(tool, user_context)

            # 4. Vérification de la confirmation explicite
            if tool.confirmation_required and not confirmed:
                raise ConfirmationRequiredError(tool_name)

            # 5. Validation des arguments
            is_valid, err_msg, err_details = ArgumentValidator.validate(tool.input_schema, arguments)
            if not is_valid:
                raise InvalidArgumentsError(
                    err_msg or "Arguments fournis non conformes au schéma de l'outil.",
                    details=err_details
                )

            # 6. Préparation du payload avec contexte vérifié
            execution_payload = dict(arguments)
            execution_payload["_context"] = {
                "user_id": user_id,
                "username": user_context.get("username"),
                "is_sudo": user_context.get("is_sudo", False),
                "branch_id": branch_id,
                "correlation_id": correlation_id,
                "tool_name": tool_name,
                "module_name": tool.module,
            }

            # 7. Exécution avec timeout contrôlé
            result = await self._run_handler(tool, execution_payload)

            duration_ms = round((time.monotonic() - start_time) * 1000, 2)

            # 8. Journalisation du succès
            await self.auditor.record_execution(
                tool_name=tool.name,
                module_name=tool.module,
                status="SUCCESS",
                duration_ms=duration_ms,
                correlation_id=correlation_id,
                user_id=user_id,
                branch_id=branch_id,
            )

            # 9. Réponse structurée normalisée
            return {
                "success": True,
                "correlation_id": correlation_id,
                "data": {
                    "result": result,
                    "metadata": {
                        "tool": tool.name,
                        "module": tool.module,
                        "duration_ms": duration_ms,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                }
            }

        except MCPException as exc:
            duration_ms = round((time.monotonic() - start_time) * 1000, 2)
            module_name = tool.module if tool else "unknown"
            await self.auditor.record_execution(
                tool_name=tool_name,
                module_name=module_name,
                status="REJECTED" if exc.status_code in (401, 403, 400) else "FAILED",
                duration_ms=duration_ms,
                correlation_id=correlation_id,
                user_id=user_id,
                branch_id=branch_id,
                error_code=exc.code.value,
            )
            return exc.to_dict(correlation_id=correlation_id)

        except asyncio.TimeoutError:
            duration_ms = round((time.monotonic() - start_time) * 1000, 2)
            timeout_sec = tool.timeout_seconds if tool else 30.0
            module_name = tool.module if tool else "unknown"
            await self.auditor.record_execution(
                tool_name=tool_name,
                module_name=module_name,
                status="TIMEOUT",
                duration_ms=duration_ms,
                correlation_id=correlation_id,
                user_id=user_id,
                branch_id=branch_id,
                error_code=MCPErrorCode.EXECUTION_TIMEOUT.value,
            )
            exc = ExecutionTimeoutError(tool_name, timeout_sec)
            return exc.to_dict(correlation_id=correlation_id)

        except Exception as err:
            duration_ms = round((time.monotonic() - start_time) * 1000, 2)
            module_name = tool.module if tool else "unknown"
            await self.auditor.record_execution(
                tool_name=tool_name,
                module_name=module_name,
                status="FAILED",
                duration_ms=duration_ms,
                correlation_id=correlation_id,
                user_id=user_id,
                branch_id=branch_id,
                error_code=MCPErrorCode.BUSINESS_ERROR.value,
            )
            # Ne pas exposer la stack trace complète vers le client externe
            exc = BusinessError(f"Erreur lors de l'exécution de l'opération: {str(err)}")
            return exc.to_dict(correlation_id=correlation_id)

    def _verify_permissions(self, tool: ToolDefinition, user_context: dict[str, Any]) -> None:
        """Vérifie si l'utilisateur possède toutes les permissions requises via le système RBAC MELODI."""
        if user_context.get("is_sudo"):
            return

        if not tool.required_permissions:
            return

        from core.utils.permissions import check_user_permission

        # Charger les permissions fraîches depuis le cache RBAC de MELODI si disponible pour cet utilisateur
        user_id = user_context.get("user_id")
        live_perms = None
        if user_id and self.app and hasattr(self.app, "cache") and self.app.cache:
            perms_map = self.app.cache.get("user_permissions")
            if isinstance(perms_map, dict) and user_id in perms_map:
                live_perms = set(perms_map.get(user_id) or [])

        user_perms = live_perms if live_perms is not None else set(user_context.get("permissions") or [])
        if "*" in user_perms:
            return

        # Support wildcard matching et check_user_permission natif MELODI
        for req in tool.required_permissions:
            if live_perms is not None:
                if check_user_permission(user_context, req, app=self.app):
                    continue
                if check_user_permission(user_context, f"{tool.module}.{req}", app=self.app):
                    continue

            if req in user_perms:
                continue

            # Support préfixe module (ex: "invoicing:read" <-> "melodi_invoicing.invoicing:read")
            if f"{tool.module}.{req}" in user_perms:
                continue

            # Vérification wildcard sur préfixe
            parts = req.split(":")
            if len(parts) == 2 and (f"{parts[0]}:*" in user_perms or f"{tool.module}.{parts[0]}:*" in user_perms):
                continue

            parts_dot = req.split(".")
            if len(parts_dot) == 2 and f"{parts_dot[0]}.*" in user_perms:
                continue

            raise PermissionDeniedError(
                f"L'utilisateur ne dispose pas de la permission requise '{req}' pour cet outil.",
                details={"missing_permission": req, "tool": tool.name}
            )

    def has_tool_permission(self, tool: ToolDefinition, user_context: dict[str, Any]) -> bool:
        """Retourne True si l'utilisateur a les permissions requises pour utiliser l'outil."""
        try:
            self._verify_permissions(tool, user_context)
            return True
        except PermissionDeniedError:
            return False

    async def _run_handler(self, tool: ToolDefinition, payload: dict[str, Any]) -> Any:
        """Exécute le handler configuré sous surveillance de timeout."""
        timeout = tool.timeout_seconds
        import inspect

        async def _call():
            # Si le handler est une chaîne sous la forme "module:action_name" ou "action_name"
            if isinstance(tool.handler, str):
                if not self.app or not hasattr(self.app, "hook_manager"):
                    raise RuntimeError("HookManager indisponible dans l'application MELODI.")

                action_target = tool.handler
                if ":" in action_target:
                    target_module, action_name = action_target.split(":", 1)
                else:
                    target_module = tool.module
                    action_name = action_target

                res = self.app.hook_manager.action.execute(target_module, action_name, payload)
                if inspect.isawaitable(res):
                    return await res
                return res

            # Si le handler est un callable async directement enregistré
            elif callable(tool.handler):
                if asyncio.iscoroutinefunction(tool.handler):
                    return await tool.handler(payload)
                else:
                    return tool.handler(payload)

            else:
                raise ValueError(f"Type de handler non supporté pour l'outil '{tool.name}'.")

        return await asyncio.wait_for(_call(), timeout=timeout)
