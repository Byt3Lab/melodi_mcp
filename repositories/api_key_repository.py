from typing import Optional, List, Any
from datetime import datetime, timezone
import inspect

from sqlalchemy import select, desc
from ..models.models import MCPApiKeyModel


def mask_key(key: str) -> str:
    """Retourne une version masquée de la clé (ex: mcp_sk_abc123...4xyz)."""
    if not key:
        return ""
    if len(key) <= 12:
        return key[:4] + "..." + key[-2:]
    return key[:8] + "..." + key[-4:]


class MCPApiKeyRepository:
    """Couche d'accès aux données pour les clés d'API MCP."""

    def __init__(self, app=None):
        self.app = app

    async def create_key(
        self,
        name: str,
        key: str,
        role: str = "service",
        permissions: str = "*",
        created_by: Optional[str] = None,
        expires_at: Optional[datetime] = None,
        session=None,
    ) -> Optional[MCPApiKeyModel]:
        """Enregistre une nouvelle clé API."""
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        prefix = mask_key(key)
        api_key_obj = MCPApiKeyModel(
            name=name.strip(),
            key=key.strip(),
            key_prefix=prefix,
            role=role.strip(),
            permissions=permissions.strip(),
            is_active=True,
            created_by=created_by,
            last_used_at=None,
            expires_at=expires_at,
            created_at=now,
            updated_at=now,
        )

        async def _do_create(s):
            if hasattr(s, "add"):
                res = s.add(api_key_obj)
                if inspect.iscoroutine(res):
                    await res
            if hasattr(s, "flush"):
                res = s.flush()
                if inspect.iscoroutine(res):
                    await res
            if hasattr(s, "commit"):
                res = s.commit()
                if inspect.iscoroutine(res):
                    await res
            return api_key_obj

        if session:
            return await _do_create(session)

        if not self.app or not hasattr(self.app, "db") or not self.app.db:
            return None

        try:
            async with self.app.db.get_session() as s:
                return await _do_create(s)
        except Exception:
            return None

    async def get_by_id(self, key_id: int, session=None) -> Optional[MCPApiKeyModel]:
        """Récupère une clé API par son ID numérique."""
        stmt = select(MCPApiKeyModel).where(MCPApiKeyModel.id == key_id)

        async def _do_get(s):
            res = await s.execute(stmt)
            return res.scalar_one_or_none()

        if session:
            return await _do_get(session)
        if not self.app or not hasattr(self.app, "db") or not self.app.db:
            return None
        try:
            async with self.app.db.get_session() as s:
                return await _do_get(s)
        except Exception:
            return None

    async def get_by_key(self, key: str, session=None) -> Optional[MCPApiKeyModel]:
        """Récupère une clé API par sa valeur secrète exacte."""
        stmt = select(MCPApiKeyModel).where(MCPApiKeyModel.key == key.strip())

        async def _do_get(s):
            res = await s.execute(stmt)
            return res.scalar_one_or_none()

        if session:
            return await _do_get(session)
        if not self.app or not hasattr(self.app, "db") or not self.app.db:
            return None
        try:
            async with self.app.db.get_session() as s:
                return await _do_get(s)
        except Exception:
            return None

    async def list_keys(self, active_only: bool = False, session=None) -> List[MCPApiKeyModel]:
        """Liste l'ensemble des clés API enregistrées."""
        stmt = select(MCPApiKeyModel).order_by(desc(MCPApiKeyModel.created_at))
        if active_only:
            stmt = stmt.where(MCPApiKeyModel.is_active == True)

        async def _do_list(s):
            res = await s.execute(stmt)
            return list(res.scalars().all())

        if session:
            return await _do_list(session)
        if not self.app or not hasattr(self.app, "db") or not self.app.db:
            return []
        try:
            async with self.app.db.get_session() as s:
                return await _do_list(s)
        except Exception:
            return []

    async def update_status(self, key_id: int, is_active: bool, session=None) -> Optional[MCPApiKeyModel]:
        """Active ou désactive une clé API."""
        async def _do_update(s):
            obj = await self.get_by_id(key_id, session=s)
            if obj:
                obj.is_active = is_active
                obj.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                if hasattr(s, "flush"):
                    res = s.flush()
                    if inspect.iscoroutine(res):
                        await res
                if hasattr(s, "commit"):
                    res = s.commit()
                    if inspect.iscoroutine(res):
                        await res
            return obj

        if session:
            return await _do_update(session)
        if not self.app or not hasattr(self.app, "db") or not self.app.db:
            return None
        async with self.app.db.get_session() as s:
            return await _do_update(s)

    async def update_last_used(self, key: str, session=None) -> None:
        """Met à jour l'horodatage de dernière utilisation d'une clé."""
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        async def _do_update(s):
            obj = await self.get_by_key(key, session=s)
            if obj:
                obj.last_used_at = now
                if hasattr(s, "flush"):
                    res = s.flush()
                    if inspect.iscoroutine(res):
                        await res
                if hasattr(s, "commit"):
                    res = s.commit()
                    if inspect.iscoroutine(res):
                        await res

        try:
            if session:
                await _do_update(session)
            elif self.app and hasattr(self.app, "db") and self.app.db:
                async with self.app.db.get_session() as s:
                    await _do_update(s)
        except Exception as e:
            print(f"[melodi_mcp] Erreur update_last_used: {e}")

    async def delete_key(self, key_id: int, session=None) -> bool:
        """Supprime définitivement une clé API."""
        async def _do_delete(s):
            obj = await self.get_by_id(key_id, session=s)
            if obj:
                if hasattr(s, "delete"):
                    res = s.delete(obj)
                    if inspect.iscoroutine(res):
                        await res
                if hasattr(s, "commit"):
                    res = s.commit()
                    if inspect.iscoroutine(res):
                        await res
                return True
            return False

        if session:
            return await _do_delete(session)
        if not self.app or not hasattr(self.app, "db") or not self.app.db:
            return False
        async with self.app.db.get_session() as s:
            return await _do_delete(s)
