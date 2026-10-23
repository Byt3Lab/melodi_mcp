import time
from typing import Any, Optional
from ..repositories.audit_repository import MCPAuditRepository


class MCPAuditor:
    """Service de journalisation sécurisée des exécutions d'outils MCP.

    Garantit qu'aucune information confidentielle ou sensible n'est persistée.
    """

    def __init__(self, app=None):
        self.app = app
        self.repository = MCPAuditRepository(app)

    async def record_execution(
        self,
        tool_name: str,
        module_name: str,
        status: str,
        duration_ms: float,
        correlation_id: Optional[str] = None,
        user_id: Optional[str] = None,
        branch_id: Optional[str] = None,
        error_code: Optional[str] = None,
    ) -> None:
        """Enregistre une entrée d'audit avec durée et métadonnées d'autorisation."""
        await self.repository.log_execution(
            tool_name=tool_name,
            module_name=module_name,
            status=status,
            correlation_id=correlation_id,
            user_id=user_id,
            branch_id=branch_id,
            error_code=error_code,
            duration_ms=duration_ms,
        )

    async def list_recent_executions(
        self,
        tool_name: Optional[str] = None,
        module_name: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return await self.repository.list_logs(
            tool_name=tool_name,
            module_name=module_name,
            status=status,
            limit=limit,
            offset=offset,
        )
