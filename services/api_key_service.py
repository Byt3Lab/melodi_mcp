import secrets
import inspect
from typing import Optional, List, Any
from datetime import datetime, timedelta, timezone

from ..config import MCP_INTERNAL_KEY
from ..repositories.api_key_repository import MCPApiKeyRepository, mask_key
from ..models.models import MCPApiKeyModel

DEFAULT_EXPIRES_IN_DAYS = 30


class MCPApiKeyService:
    """Service métier de gestion du cycle de vie des clés / tokens API MCP."""

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
        role: str = "user",
        permissions: str = "*",
        created_by: Optional[str] = None,
        custom_key: Optional[str] = None,
        expires_at: Optional[datetime] = None,
        expires_in_days: Optional[int] = DEFAULT_EXPIRES_IN_DAYS,
    ) -> tuple[Optional[MCPApiKeyModel], str]:
        """Crée et persiste un nouveau token MCP (valable 7 jours par défaut)."""
        secret_key = custom_key.strip() if custom_key and custom_key.strip() else self.generate_secret_token()
        if expires_at is None and expires_in_days and expires_in_days > 0:
            expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=int(expires_in_days))

        key_obj = await self.repo.create_key(
            name=name,
            key=secret_key,
            role=role,
            permissions=permissions,
            created_by=created_by,
            expires_at=expires_at,
        )
        return key_obj, secret_key

    async def _load_user_from_melodi(self, user_id: str):
        """Charge l'utilisateur MELODI via UserRepository."""
        if not self.app or not hasattr(self.app, "module_manager") or not self.app.module_manager:
            return None
        try:
            from base.repositories.user_repository import UserRepository
            base_module = self.app.module_manager.get_module("base") if hasattr(self.app.module_manager, "get_module") else None
            if not base_module and hasattr(self.app.module_manager, "modules"):
                base_module = self.app.module_manager.modules.get("base")
            if not base_module:
                return None
            user_repo = UserRepository(base_module)
            return await user_repo.get_user_by_id(user_id)
        except Exception:
            return None

    async def verify_key(self, raw_key: str) -> Optional[dict[str, Any]]:
        """Vérifie l'authenticité et la validité d'un token MCP et charge l'utilisateur et ses permissions."""
        if not raw_key or not raw_key.strip():
            return None

        clean_key = raw_key.strip()

        # 1. Vérification en base de données
        key_obj = await self.repo.get_by_key(clean_key)
        if key_obj:
            if not key_obj.is_active:
                return None

            # Vérifier l'expiration (7 jours par défaut)
            if getattr(key_obj, "expires_at", None) and isinstance(key_obj.expires_at, datetime):
                now = datetime.now(timezone.utc).replace(tzinfo=None)
                exp = key_obj.expires_at.replace(tzinfo=None) if getattr(key_obj.expires_at, "tzinfo", None) else key_obj.expires_at
                if now > exp:
                    return None

            # Mettre à jour last_used_at
            await self.repo.update_last_used(clean_key)

            key_perms = []
            if isinstance(getattr(key_obj, "permissions", None), str):
                key_perms = [p.strip() for p in key_obj.permissions.split(",") if p.strip()]

            # Cas A: Token rattaché à un utilisateur MELODI réel
            owner_user_id = getattr(key_obj, "created_by", None)
            if isinstance(owner_user_id, (str, int)) and str(owner_user_id).strip() not in ("", "system"):
                owner_user_id = str(owner_user_id).strip()
                user = await self._load_user_from_melodi(owner_user_id)
                if user is not None and not getattr(user, "is_active", True):
                    # L'utilisateur propriétaire a été désactivé
                    return None

                # Récupérer les permissions actuelles de l'utilisateur depuis le cache RBAC de MELODI
                cache_perms = []
                active_branch = None
                if self.app and hasattr(self.app, "cache") and self.app.cache:
                    permissions_map = self.app.cache.get("user_permissions") or {}
                    cache_perms = list(permissions_map.get(owner_user_id, []))
                    branches_map = self.app.cache.get("user_branches") or {}
                    user_branches = branches_map.get(owner_user_id, [])
                    if user_branches:
                        active_branch = user_branches[0]

                is_sudo = bool(getattr(user, "is_sudo", False)) if user is not None else False
                username = getattr(user, "username", None) or key_obj.name

                return {
                    "user_id": owner_user_id,
                    "username": username,
                    "is_sudo": is_sudo,
                    "permissions": cache_perms,
                    "active_branch": active_branch,
                    "role": key_obj.role,
                    "auth_type": "api_key",
                    "key_id": key_obj.id,
                }

            # Cas B: Clé de service ou clé sans propriétaire utilisateur spécifique
            is_sudo = ("*" in key_perms) or (key_obj.role in ("admin", "service"))

            return {
                "user_id": f"api_key_{key_obj.id}",
                "username": key_obj.name,
                "is_sudo": is_sudo,
                "permissions": key_perms,
                "role": key_obj.role,
                "auth_type": "api_key",
                "key_id": key_obj.id,
            }

        # 2. Secours: vérification avec la clé d'environnement partagée MCP_INTERNAL_KEY ou stockée
        current_internal = self.get_internal_key()
        if clean_key == current_internal or clean_key == MCP_INTERNAL_KEY:
            return {
                "user_id": "service_mcp",
                "username": "melodi_mcp_internal_service",
                "is_sudo": True,
                "permissions": ["*"],
                "role": "service",
                "auth_type": "service_key",
            }

        return None

    async def list_keys(self, user_id: Optional[str] = None) -> List[dict[str, Any]]:
        """Liste les clés API (filtrées par utilisateur si user_id est fourni)."""
        objs = await self.repo.list_keys()
        res = []
        for o in objs:
            if user_id and getattr(o, "created_by", None) != user_id:
                continue
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

    def get_internal_key(self) -> str:
        """Récupère la clé d'authentification interne active depuis la config mémoire."""
        import modules.melodi_mcp.config as mcp_cfg
        return getattr(mcp_cfg, "MCP_INTERNAL_KEY", "mcp-internal-secret-token")

    async def load_persisted_internal_key(self) -> str:
        """Charge la clé interne stockée en base de données dans la configuration mémoire."""
        import modules.melodi_mcp.config as mcp_cfg
        if self.app and hasattr(self.app, "db") and self.app.db:
            try:
                from base.repositories.setting_repository import SettingRepository
                setting_repo = SettingRepository(self.app)
                val = await setting_repo.get_setting("melodi_mcp_internal_key")
                if val and val.strip():
                    mcp_cfg.MCP_INTERNAL_KEY = val.strip()
                    return val.strip()
            except Exception:
                pass
        return getattr(mcp_cfg, "MCP_INTERNAL_KEY", "mcp-internal-secret-token")

    async def update_internal_key(self, new_key: str) -> str:
        """Met à jour et persiste la clé d'authentification interne du serveur MCP."""
        import inspect
        import modules.melodi_mcp.config as mcp_cfg
        clean_key = new_key.strip() if new_key else self.generate_secret_token(prefix="mcp_internal_")
        if not clean_key:
            clean_key = self.generate_secret_token(prefix="mcp_internal_")

        mcp_cfg.MCP_INTERNAL_KEY = clean_key
        if self.app and hasattr(self.app, "config"):
            setattr(self.app.config, "MELODI_MCP_INTERNAL_KEY", clean_key)

        # 1. Sauvegarde dans SettingRepository
        if self.app and hasattr(self.app, "db") and self.app.db:
            try:
                from base.repositories.setting_repository import SettingRepository
                setting_repo = SettingRepository(self.app)
                await setting_repo.set_setting("melodi_mcp_internal_key", clean_key)
            except Exception as e:
                print(f"[melodi_mcp] Erreur sauvegarde setting interne: {e}")

            # 2. Mise à jour ou création de la clé correspondante dans MCPApiKeyModel
            try:
                keys = await self.repo.list_keys()
                system_key = next((k for k in keys if getattr(k, "created_by", None) == "system" or getattr(k, "role", None) == "service"), None)
                if system_key:
                    async with self.app.db.get_session() as s:
                        obj = await self.repo.get_by_id(system_key.id, session=s)
                        if obj:
                            obj.key = clean_key
                            obj.key_prefix = mask_key(clean_key)
                            obj.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                            if hasattr(s, "commit"):
                                res = s.commit()
                                if inspect.isawaitable(res):
                                    await res
                else:
                    await self.repo.create_key(
                        name="Clé de Service Interne Principale",
                        key=clean_key,
                        role="service",
                        permissions="*",
                        created_by="system",
                    )
            except Exception as e:
                print(f"[melodi_mcp] Erreur sync clé API table: {e}")

        return clean_key

    async def ensure_default_key(self) -> None:
        """Assure la présence d'au moins une clé de service active initialisée."""
        if not self.app or not hasattr(self.app, "db") or not self.app.db:
            return

        try:
            current_key = self.get_internal_key()
            if inspect.iscoroutine(current_key):
                current_key = await current_key
            existing = await self.repo.list_keys()
            if not existing:
                await self.repo.create_key(
                    name="Clé de Service Interne Principale",
                    key=current_key,
                    role="service",
                    permissions="*",
                    created_by="system",
                )
                print(f"[melodi_mcp] Clé API par défaut initialisée ({mask_key(current_key)}).")
        except Exception as e:
            # Ne pas bloquer l'initialisation si la table n'est pas encore migrée
            print(f"[melodi_mcp] Notice ensure_default_key: {e}")
