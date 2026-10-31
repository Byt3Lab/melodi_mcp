import secrets
import inspect
import re
from typing import Optional, List, Any
from datetime import datetime, timedelta, timezone

from jose import jwt as jose_jwt, JWTError

from ..config import MCP_INTERNAL_KEY, MCP_SERVER_URL, MCP_SERVER_API_KEY, MCP_JWT_SECRET
from ..repositories.api_key_repository import MCPApiKeyRepository, mask_key
from ..models.models import MCPApiKeyModel

DEFAULT_EXPIRES_IN_HOURS = 24


class MCPApiKeyService:
    """Service métier de gestion du cycle de vie des clés et jetons JWT MCP."""

    def __init__(self, app=None):
        self.app = app
        self.repo = MCPApiKeyRepository(app=app)

    @staticmethod
    def generate_secret_token(prefix: str = "mcp_live_") -> str:
        """Génère un jeton cryptographique aléatoire sécurisé."""
        random_bytes = secrets.token_urlsafe(32)
        return f"{prefix}{random_bytes}"

    def get_jwt_secret(self) -> str:
        """Récupère la clé secrète JWT active."""
        import modules.melodi_mcp.config as mcp_cfg
        return getattr(mcp_cfg, "MCP_JWT_SECRET", MCP_JWT_SECRET)

    async def update_jwt_secret(self, new_secret: str) -> str:
        """Met à jour et persiste la clé secrète JWT pour melodi_mcp."""
        import modules.melodi_mcp.config as mcp_cfg
        clean_secret = new_secret.strip() if new_secret and new_secret.strip() else secrets.token_urlsafe(32)
        mcp_cfg.MCP_JWT_SECRET = clean_secret
        if self.app and hasattr(self.app, "config"):
            setattr(self.app.config, "MELODI_MCP_JWT_SECRET", clean_secret)
        if self.app and hasattr(self.app, "db") and self.app.db:
            try:
                from base.repositories.setting_repository import SettingRepository
                setting_repo = SettingRepository(self.app)
                await setting_repo.set_setting("melodi_mcp_jwt_secret", clean_secret)
            except Exception as e:
                print(f"[melodi_mcp] Erreur sauvegarde setting jwt_secret: {e}")
        return clean_secret

    def get_server_api_key(self) -> str:
        """Récupère la clé d'infrastructure MCP serveur (mcp_api_key)."""
        import modules.melodi_mcp.config as mcp_cfg
        return getattr(mcp_cfg, "MCP_SERVER_API_KEY", MCP_SERVER_API_KEY)

    async def update_server_api_key(self, new_key: str) -> str:
        """Met à jour et persiste la clé d'infrastructure MCP serveur."""
        import modules.melodi_mcp.config as mcp_cfg
        clean_key = new_key.strip()
        mcp_cfg.MCP_SERVER_API_KEY = clean_key
        if self.app and hasattr(self.app, "config"):
            setattr(self.app.config, "MCP_API_KEY", clean_key)
        if self.app and hasattr(self.app, "db") and self.app.db:
            try:
                from base.repositories.setting_repository import SettingRepository
                setting_repo = SettingRepository(self.app)
                await setting_repo.set_setting("melodi_mcp_server_api_key", clean_key)
            except Exception as e:
                print(f"[melodi_mcp] Erreur sauvegarde setting server_api_key: {e}")
        return clean_key

    def get_server_url(self) -> str:
        """Récupère l'URL du serveur MCP."""
        import modules.melodi_mcp.config as mcp_cfg
        return getattr(mcp_cfg, "MCP_SERVER_URL", MCP_SERVER_URL)

    async def update_server_url(self, new_url: str) -> str:
        """Met à jour et persiste l'URL du serveur MCP."""
        import modules.melodi_mcp.config as mcp_cfg
        clean_url = new_url.strip()
        mcp_cfg.MCP_SERVER_URL = clean_url
        if self.app and hasattr(self.app, "config"):
            setattr(self.app.config, "MCP_SERVER_URL", clean_url)
        if self.app and hasattr(self.app, "db") and self.app.db:
            try:
                from base.repositories.setting_repository import SettingRepository
                setting_repo = SettingRepository(self.app)
                await setting_repo.set_setting("melodi_mcp_server_url", clean_url)
            except Exception as e:
                print(f"[melodi_mcp] Erreur sauvegarde setting server_url: {e}")
        return clean_url

    async def create_key(
        self,
        name: str,
        role: str = "user",
        permissions: str = "*",
        created_by: Optional[str] = None,
        custom_key: Optional[str] = None,
        expires_at: Optional[datetime] = None,
        expires_in_hours: Optional[int] = DEFAULT_EXPIRES_IN_HOURS,
        expires_in_days: Optional[int] = None,
    ) -> tuple[Optional[MCPApiKeyModel], str]:
        """Crée et persiste un nouveau jeton JWT MCP (durée obligatoire entre 1h et 72h max)."""
        now_dt = datetime.now(timezone.utc)

        # Calcul de la durée en heures (min 1h, max 72h)
        if expires_in_days is not None:
            hours = int(expires_in_days) * 24
        elif expires_in_hours is not None:
            hours = int(expires_in_hours)
        else:
            hours = DEFAULT_EXPIRES_IN_HOURS

        hours = max(1, min(72, hours))

        if expires_at is None:
            exp_dt = now_dt + timedelta(hours=hours)
            expires_at = exp_dt.replace(tzinfo=None)
            exp_timestamp = int(exp_dt.timestamp())
        else:
            exp_aware = expires_at.replace(tzinfo=timezone.utc) if expires_at.tzinfo is None else expires_at
            exp_timestamp = int(exp_aware.timestamp())

        token_id = f"tok_{secrets.token_hex(8)}"
        user_id_str = str(created_by or "system")

        if custom_key and custom_key.strip():
            secret_key = custom_key.strip()
        else:
            payload = {
                "token_id": token_id,
                "user_id": user_id_str,
                "mcp_api_key": self.get_server_api_key(),
                "exp": exp_timestamp,
                "iat": int(now_dt.timestamp()),
            }
            jwt_token = jose_jwt.encode(payload, self.get_jwt_secret(), algorithm="HS256")
            if isinstance(jwt_token, bytes):
                jwt_token = jwt_token.decode("utf-8")
            secret_key = jwt_token

        key_obj = await self.repo.create_key(
            name=name,
            key=secret_key,
            role=role,
            permissions=permissions,
            created_by=created_by,
            expires_at=expires_at,
            key_prefix=token_id,
        )
        return key_obj, secret_key

    async def notify_mcp_server_revocation(
        self,
        token_id: str,
        user_id: Optional[str] = None,
        reason: str = "revoked_by_user",
    ) -> bool:
        """Notifie melodi_mcp_server de la révocation d'un token pour l'ajouter à sa liste de blocage."""
        if not token_id or not str(token_id).strip():
            return False

        server_url = self.get_server_url()
        clean_url = server_url.rstrip("/")
        for suffix in ("/mcp", "/sse"):
            if clean_url.endswith(suffix):
                clean_url = clean_url[:-len(suffix)].rstrip("/")
                break

        revoke_url = f"{clean_url}/api/mcp/tokens/revoke"
        internal_key = self.get_internal_key()

        headers = {
            "Authorization": f"Bearer {internal_key}",
            "X-Internal-MCP-Key": internal_key,
            "Content-Type": "application/json",
        }
        payload = {
            "token_id": str(token_id).strip(),
            "user_id": str(user_id) if user_id else None,
            "reason": reason,
        }

        try:
            import httpx
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.post(revoke_url, json=payload, headers=headers)
                return resp.status_code == 200
        except Exception as e:
            print(f"[melodi_mcp] Notice: Notification de révocation à melodi_mcp_server ({revoke_url}) : {e}")
            return False

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

        # 1. Tentative de décodage comme jeton JWT
        try:
            payload = jose_jwt.decode(clean_key, self.get_jwt_secret(), algorithms=["HS256"])
            if payload and isinstance(payload, dict):
                token_id = payload.get("token_id") or payload.get("jti")
                user_id = payload.get("user_id") or payload.get("sub")

                # Vérifier si révoqué en base de données
                if token_id:
                    key_obj = await self.repo.get_by_key(token_id)
                    if key_obj and not key_obj.is_active:
                        return None
                    if key_obj:
                        await self.repo.update_last_used(key_obj.key)

                if user_id and str(user_id).strip() not in ("", "system"):
                    user_id = str(user_id).strip()
                    user = await self._load_user_from_melodi(user_id)
                    if user is not None and not getattr(user, "is_active", True):
                        return None

                    cache_perms = []
                    active_branch = None
                    if self.app and hasattr(self.app, "cache") and self.app.cache:
                        permissions_map = self.app.cache.get("user_permissions") or {}
                        cache_perms = list(permissions_map.get(user_id, []))
                        branches_map = self.app.cache.get("user_branches") or {}
                        user_branches = branches_map.get(user_id, [])
                        if user_branches:
                            active_branch = user_branches[0]

                    is_sudo = bool(getattr(user, "is_sudo", False)) if user is not None else False
                    username = getattr(user, "username", None) or user_id

                    return {
                        "user_id": user_id,
                        "username": username,
                        "is_sudo": is_sudo,
                        "permissions": cache_perms,
                        "active_branch": active_branch,
                        "role": "user",
                        "auth_type": "jwt",
                        "token_id": token_id,
                    }
        except Exception:
            pass

        # 2. Vérification directe en base de données (pour clés API ou tests unitaires)
        key_obj = await self.repo.get_by_key(clean_key)
        if key_obj:
            if not key_obj.is_active:
                return None

            # Vérifier l'expiration
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
                    return None

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

        # 3. Secours: vérification avec la clé d'environnement partagée MCP_INTERNAL_KEY ou stockée
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
        """Active ou désactive une clé API et notifie melodi_mcp_server si révoquée."""
        key_obj = await self.repo.get_by_id(key_id)
        if not key_obj:
            return None
        new_status = not key_obj.is_active
        updated = await self.repo.update_status(key_id, new_status)
        if updated and not new_status:
            # Token désactivé -> notification au serveur MCP pour l'ajouter à sa table des tokens révoqués
            token_id = getattr(key_obj, "key_prefix", None) or getattr(key_obj, "key", None)
            if token_id:
                await self.notify_mcp_server_revocation(
                    token_id=token_id,
                    user_id=getattr(key_obj, "created_by", None),
                    reason="deactivated_by_user",
                )
        return updated.to_dict() if updated else None

    async def delete_key(self, key_id: int) -> bool:
        """Supprime une clé API et signale sa révocation définitive à melodi_mcp_server."""
        key_obj = await self.repo.get_by_id(key_id)
        token_id = getattr(key_obj, "key_prefix", None) or getattr(key_obj, "key", None) if key_obj else None
        user_id = getattr(key_obj, "created_by", None) if key_obj else None

        deleted = await self.repo.delete_key(key_id)
        if deleted and token_id:
            await self.notify_mcp_server_revocation(
                token_id=token_id,
                user_id=user_id,
                reason="deleted_by_user",
            )
        return deleted

    def get_internal_key(self) -> str:
        """Récupère la clé d'authentification interne active depuis la config mémoire."""
        import modules.melodi_mcp.config as mcp_cfg
        return getattr(mcp_cfg, "MCP_INTERNAL_KEY", MCP_INTERNAL_KEY)

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
        return getattr(mcp_cfg, "MCP_INTERNAL_KEY", MCP_INTERNAL_KEY)

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
            print(f"[melodi_mcp] Notice ensure_default_key: {e}")
