from datetime import datetime
from typing import Optional

from core.orm.model import (
    BaseModel,
    Mapped,
    mapped_column,
    Integer,
    String,
    Float,
    DateTime,
    Text,
)
from ..config import MCPTables


class MCPAuditLogModel(BaseModel):
    """Journal d'audit des exécutions d'outils MCP."""
    __tablename__ = MCPTables.AUDIT_LOGS

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    correlation_id: Mapped[Optional[str]] = mapped_column(String(100), index=True, nullable=True)
    tool_name: Mapped[str] = mapped_column(String(150), index=True)
    module_name: Mapped[str] = mapped_column(String(100), index=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    branch_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(50))  # SUCCESS, FAILED, REJECTED, TIMEOUT
    error_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "correlation_id": self.correlation_id,
            "tool_name": self.tool_name,
            "module_name": self.module_name,
            "user_id": self.user_id,
            "branch_id": self.branch_id,
            "status": self.status,
            "error_code": self.error_code,
            "duration_ms": self.duration_ms,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
