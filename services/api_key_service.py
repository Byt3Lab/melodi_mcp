import secrets
from typing import Optional, List, Any
from datetime import datetime, timezone

from ..config import MCP_INTERNAL_KEY
from ..repositories.api_key_repository import MCPApiKeyRepository, mask_key
from ..models.models import MCPApiKeyModel


class MCPApiKeyService:
    """Service métier de gestion du cycle de vie des clés API MCP."""

    def __init__(self, app=None):
        self.app = app
        self.repo = MCPApiKeyRepository(app=app)

    @staticmethod
    def generate_secret_token(prefix: str = "mcp_live_") -> str:
        """Génère un jeton cryptographique aléatoire sécurisé."""
        random_bytes = secrets.token_urlsafe(32)
        return f"{prefix}{random_bytes}"

    async def create_key(
        self,
        name: str,
        role: str = "service",
        permissions: str = "*",
        created_by: Optional[str] = None,
        custom_key: Optional[str] = None,
        expires_at: Optional[datetime] = None,
    ) -> tuple[Optional[MCPApiKeyModel], str]:
        """Crée et persiste une nouvelle clé API MCP."""
        secret_key = custom_key.strip() if custom_key and custom_key.strip() else self.generate_secret_token()
        key_obj = await self.repo.create_key(
            name=name,
            key=secret_key,
            role=role,
            permissions=permissions,
            created_by=created_by,
            expires_at=expires_at,
        )
        return key_obj, secret_key

    async def verify_key(self, raw_key: str) -> Optional[dict[str, Any]]:
        """Vérifie l'authenticité et la validité d'une clé API et met à jour son horodatage."""
        if not raw_key or not raw_key.strip():
            return None

        clean_key = raw_key.strip()

        # 1. Vérification en base de données
        key_obj = await self.repo.get_by_key(clean_key)
        if key_obj:
            if not key_obj.is_active:
                return None

            # Vérifier l'expiration éventuelle
            if key_obj.expires_at:
                now = datetime.now(timezone.utc).replace(tzinfo=None)
                if now > key_obj.expires_at:
                    return None

            # Mettre à jour last_used_at en arrière-plan
            await self.repo.update_last_used(clean_key)

            # Extraire les permissions
            perms = [p.strip() for p in key_obj.permissions.split(",") if p.strip()] if key_obj.permissions else []
            is_sudo = ("*" in perms) or (key_obj.role in ("admin", "service"))

            return {
                "user_id": f"api_key_{key_obj.id}",
                "username": key_obj.name,
                "is_sudo": is_sudo,
                "permissions": perms,
                "role": key_obj.role,
                "auth_type": "api_key",
                "key_id": key_obj.id,
            }

        # 2. Secours: vérification avec la clé d'environnement partagée MCP_INTERNAL_KEY
        if clean_key == MCP_INTERNAL_KEY:
            return {
                "user_id": "service_mcp",
                "username": "melodi_mcp_internal_service",
                "is_sudo": True,
                "permissions": ["*"],
                "role": "service",
                "auth_type": "service_key",
            }

        return None

    async def list_keys(self) -> List[dict[str, Any]]:
        """Liste toutes les clés API sous forme de dictionnaires sérialisables."""
        objs = await self.repo.list_keys()
        res = []
        for o in objs:
            d = o.to_dict()
            res.append(d)
        return res

    async def toggle_status(self, key_id: int) -> Optional[dict[str, Any]]:
        """Active ou désactive une clé API."""
        key_obj = await self.repo.get_by_id(key_id)
        if not key_obj:
            return None
        updated = await self.repo.update_status(key_id, not key_obj.is_active)
        return updated.to_dict() if updated else None

    async def delete_key(self, key_id: int) -> bool:
        """Supprime une clé API."""
        return await self.repo.delete_key(key_id)

    async def ensure_default_key(self) -> None:
        """Assure la présence d'au moins une clé de service active initialisée."""
        if not self.app or not hasattr(self.app, "db") or not self.app.db:
            return

        try:
            existing = await self.repo.list_keys()
            if not existing:
                await self.repo.create_key(
                    name="Clé de Service Interne Principale",
                    key=MCP_INTERNAL_KEY,
                    role="service",
                    permissions="*",
                    created_by="system",
                )
                print(f"[melodi_mcp] Clé API par défaut initialisée ({mask_key(MCP_INTERNAL_KEY)}).")
        except Exception as e:
            # Ne pas bloquer l'initialisation si la table n'est pas encore migrée
            print(f"[melodi_mcp] Notice ensure_default_key: {e}")
