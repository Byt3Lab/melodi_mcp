from datetime import datetime, timezone
from typing import Optional

from core.orm.model import (
    BaseModel,
    Mapped,
    mapped_column,
    Integer,
    String,
    Float,
    Boolean,
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

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


class MCPApiKeyModel(BaseModel):
    """Clé d'authentification API pour melodi_mcp et clients MCP externes."""
    __tablename__ = MCPTables.API_KEYS

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(150))
    key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    key_prefix: Mapped[str] = mapped_column(String(30))
    role: Mapped[str] = mapped_column(String(50), default="service")
    permissions: Mapped[str] = mapped_column(Text, default="*")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "key": self.key,
            "key_prefix": self.key_prefix,
            "role": self.role,
            "permissions": [p.strip() for p in self.permissions.split(",") if p.strip()] if self.permissions else [],
            "is_active": self.is_active,
            "created_by": self.created_by,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
