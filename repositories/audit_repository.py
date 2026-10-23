from typing import Optional, List
from datetime import datetime, timezone
import inspect

from sqlalchemy import select, desc
from ..models.models import MCPAuditLogModel


class MCPAuditRepository:
    """Gestion des enregistrements d'audit en base de données."""

    def __init__(self, app=None):
        self.app = app

    async def log_execution(
        self,
        tool_name: str,
        module_name: str,
        status: str,
        correlation_id: Optional[str] = None,
        user_id: Optional[str] = None,
        branch_id: Optional[str] = None,
        error_code: Optional[str] = None,
        duration_ms: float = 0.0,
    ) -> Optional[MCPAuditLogModel]:
        """Crée une entrée d'audit en base."""
        if not self.app or not hasattr(self.app, "db") or not self.app.db:
            return None

        try:
            async with self.app.db.get_session() as session:
                log_entry = MCPAuditLogModel(
                    correlation_id=correlation_id,
                    tool_name=tool_name,
                    module_name=module_name,
                    user_id=user_id,
                    branch_id=branch_id,
                    status=status,
                    error_code=error_code,
                    duration_ms=duration_ms,
                    created_at=datetime.now(timezone.utc),
                )
                if hasattr(session, "add"):
                    res = session.add(log_entry)
                    if inspect.iscoroutine(res):
                        await res
                if hasattr(session, "commit"):
                    res = session.commit()
                    if inspect.iscoroutine(res):
                        await res
                return log_entry
        except Exception as e:
            # Ne jamais bloquer l'ERP si l'enregistrement de journal échoue
            print(f"[melodi_mcp] Erreur lors de l'enregistrement de l'audit: {e}")
            return None

    async def list_logs(
        self,
        tool_name: Optional[str] = None,
        module_name: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[dict]:
        """Récupère les entrées d'audit paginées."""
        if not self.app or not hasattr(self.app, "db") or not self.app.db:
            return []

        try:
            async with self.app.db.get_session() as session:
                stmt = select(MCPAuditLogModel).order_by(desc(MCPAuditLogModel.created_at))
                if tool_name:
                    stmt = stmt.where(MCPAuditLogModel.tool_name == tool_name)
                if module_name:
                    stmt = stmt.where(MCPAuditLogModel.module_name == module_name)
                if status:
                    stmt = stmt.where(MCPAuditLogModel.status == status)

                stmt = stmt.offset(offset).limit(limit)
                result = await session.execute(stmt)
                records = result.scalars().all()
                return [r.to_dict() for r in records]
        except Exception as e:
            print(f"[melodi_mcp] Erreur lors de la lecture des logs d'audit: {e}")
            return []
