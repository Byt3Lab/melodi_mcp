import base64
import hashlib
import logging
import secrets
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("melodi_mcp.oauth")


class MCPOAuthService:
    """Service de gestion des codes d'autorisation OAuth 2.0 avec validation PKCE (RFC 7636)."""

    _instance: Optional["MCPOAuthService"] = None
    _lock = threading.Lock()

    def __init__(self, app=None):
        self.app = app
        self._codes: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def get_instance(cls, app=None) -> "MCPOAuthService":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(app=app)
            elif app and cls._instance.app is None:
                cls._instance.app = app
            return cls._instance

    def create_authorization_code(
        self,
        client_id: str,
        redirect_uri: str,
        user_id: str,
        code_challenge: Optional[str] = None,
        code_challenge_method: Optional[str] = None,
        ttl_seconds: int = 300,
    ) -> str:
        """Génère un code d'autorisation temporaire (5 minutes par défaut) lié à l'utilisateur."""
        code = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=ttl_seconds)

        with self._lock:
            # Nettoyage automatique des vieux codes expirés
            self._cleanup_expired()

            self._codes[code] = {
                "code": code,
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "user_id": str(user_id),
                "code_challenge": code_challenge,
                "code_challenge_method": (code_challenge_method or "S256").upper() if code_challenge else None,
                "expires_at": expires_at,
                "used": False,
            }

        logger.info(
            "Code d'autorisation OAuth 2.0 généré pour user '%s' et client '%s' (expire à %s)",
            user_id,
            client_id,
            expires_at.isoformat(),
        )
        return code

    def consume_authorization_code(
        self,
        code: str,
        client_id: str,
        redirect_uri: Optional[str] = None,
        code_verifier: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Valide et consomme atomiquement un code d'autorisation (usage unique).

        Vérifie :
        - Présence du code et statut non utilisé
        - Expiration temporelle
        - Concordance de client_id et redirect_uri
        - Validation cryptographique PKCE (S256 ou plain)
        """
        if not code or not str(code).strip():
            return None

        clean_code = str(code).strip()
        now = datetime.now(timezone.utc)

        with self._lock:
            record = self._codes.get(clean_code)
            if not record:
                logger.warning("Code d'autorisation OAuth 2.0 introuvable : %s", clean_code)
                return None

            if record["used"]:
                logger.warning("Tentative de réutilisation du code OAuth 2.0 : %s", clean_code)
                return None

            if record["expires_at"] <= now:
                logger.warning("Code d'autorisation OAuth 2.0 expiré : %s", clean_code)
                return None

            # Vérification du client_id si fourni
            expected_client = record["client_id"]
            if client_id and client_id != expected_client:
                logger.warning(
                    "Client ID incompatible (attendu: %s, reçu: %s)",
                    expected_client,
                    client_id,
                )
                return None

            # Vérification du redirect_uri si fourni
            if redirect_uri and record["redirect_uri"] != redirect_uri:
                logger.warning(
                    "redirect_uri incompatible (attendu: %s, reçu: %s)",
                    record["redirect_uri"],
                    redirect_uri,
                )
                return None

            # Vérification PKCE (RFC 7636)
            challenge = record["code_challenge"]
            if challenge:
                if not code_verifier:
                    logger.warning("code_verifier manquant pour la validation PKCE.")
                    return None

                method = record["code_challenge_method"] or "S256"
                if method == "S256":
                    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
                    computed = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
                    if not secrets.compare_digest(computed, challenge.rstrip("=")):
                        logger.warning("Échec de la validation PKCE S256.")
                        return None
                elif method == "PLAIN":
                    if not secrets.compare_digest(code_verifier, challenge):
                        logger.warning("Échec de la validation PKCE PLAIN.")
                        return None
                else:
                    logger.warning("Méthode de challenge PKCE non supportée : %s", method)
                    return None

            # Marquer le code comme consommé (protection anti-rejeu)
            record["used"] = True

        return record

    def _cleanup_expired(self):
        """Supprime les codes expirés de la mémoire."""
        now = datetime.now(timezone.utc)
        expired_keys = [k for k, v in self._codes.items() if v["expires_at"] <= now or v["used"]]
        for k in expired_keys:
            del self._codes[k]
