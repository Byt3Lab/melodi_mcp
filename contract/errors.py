from enum import Enum
from typing import Any, Optional


class MCPErrorCode(str, Enum):
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
    TOOL_DISABLED = "TOOL_DISABLED"
    MODULE_UNAVAILABLE = "MODULE_UNAVAILABLE"
    INVALID_ARGUMENTS = "INVALID_ARGUMENTS"
    INVALID_BUSINESS_CONTEXT = "INVALID_BUSINESS_CONTEXT"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    CONTRACT_VERSION_CONFLICT = "CONTRACT_VERSION_CONFLICT"
    EXECUTION_TIMEOUT = "EXECUTION_TIMEOUT"
    BUSINESS_ERROR = "BUSINESS_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class MCPException(Exception):
    """Exception de base pour les erreurs du module melodi_mcp."""
    def __init__(
        self,
        code: MCPErrorCode,
        message: str,
        status_code: int = 400,
        details: Optional[dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}

    def to_dict(self, correlation_id: Optional[str] = None) -> dict[str, Any]:
        resp: dict[str, Any] = {
            "success": False,
            "error": {
                "code": self.code.value,
                "message": self.message,
            }
        }
        if correlation_id:
            resp["correlation_id"] = correlation_id
        if self.details:
            resp["error"]["details"] = self.details
        return resp


class AuthenticationRequiredError(MCPException):
    def __init__(self, message: str = "Authentification requise pour accéder à l'API interne MCP.", details: Optional[dict] = None):
        super().__init__(MCPErrorCode.AUTHENTICATION_REQUIRED, message, status_code=401, details=details)


class PermissionDeniedError(MCPException):
    def __init__(self, message: str = "Droits insuffisants pour exécuter cette opération.", details: Optional[dict] = None):
        super().__init__(MCPErrorCode.PERMISSION_DENIED, message, status_code=403, details=details)


class ToolNotFoundError(MCPException):
    def __init__(self, tool_name: str, details: Optional[dict] = None):
        super().__init__(MCPErrorCode.TOOL_NOT_FOUND, f"L'outil '{tool_name}' est introuvable dans le catalogue.", status_code=404, details=details)


class ToolDisabledError(MCPException):
    def __init__(self, tool_name: str, details: Optional[dict] = None):
        super().__init__(MCPErrorCode.TOOL_DISABLED, f"L'outil '{tool_name}' est actuellement désactivé.", status_code=400, details=details)


class ModuleUnavailableError(MCPException):
    def __init__(self, module_name: str, details: Optional[dict] = None):
        super().__init__(MCPErrorCode.MODULE_UNAVAILABLE, f"Le module propriétaire '{module_name}' est inactif ou non disponible.", status_code=503, details=details)


class InvalidArgumentsError(MCPException):
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(MCPErrorCode.INVALID_ARGUMENTS, message, status_code=422, details=details)


class ConfirmationRequiredError(MCPException):
    def __init__(self, tool_name: str, details: Optional[dict] = None):
        super().__init__(MCPErrorCode.CONFIRMATION_REQUIRED, f"L'outil destructif ou sensible '{tool_name}' requiert une confirmation explicite (confirmed: true).", status_code=400, details=details)


class ExecutionTimeoutError(MCPException):
    def __init__(self, tool_name: str, timeout_seconds: float, details: Optional[dict] = None):
        super().__init__(MCPErrorCode.EXECUTION_TIMEOUT, f"Le délai d'exécution de l'outil '{tool_name}' a été dépassé ({timeout_seconds}s).", status_code=504, details=details)


class BusinessError(MCPException):
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(MCPErrorCode.BUSINESS_ERROR, message, status_code=400, details=details)


class ContractVersionConflictError(MCPException):
    def __init__(self, client_version: str, supported_version: str, details: Optional[dict] = None):
        super().__init__(
            MCPErrorCode.CONTRACT_VERSION_CONFLICT,
            f"Version de contrat incompatible. Reçu '{client_version}', requis '{supported_version}'.",
            status_code=409,
            details=details or {"client_version": client_version, "supported_version": supported_version}
        )
