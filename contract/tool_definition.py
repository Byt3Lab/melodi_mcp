from dataclasses import dataclass, field
import re
from typing import Any, Callable, Optional, Union

# Pattern: alphanumeric, underscores or hyphens, between 3 and 80 characters
TOOL_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_\-\.]{3,80}$")


@dataclass
class ToolDefinition:
    """Définition d'un outil MCP exposé par un module MELODI."""
    name: str
    description: str
    input_schema: dict[str, Any]
    module: str
    version: str = "1.0.0"
    enabled: bool = True
    required_permissions: list[str] = field(default_factory=list)
    handler: Union[str, Callable] = ""
    read_only: bool = True
    destructive: bool = False
    category: str = "general"
    output_schema: Optional[dict[str, Any]] = None
    confirmation_required: bool = False
    timeout_seconds: float = 30.0
    idempotent: bool = False

    def validate(self) -> None:
        """Valide la cohérence et l'intégrité de la déclaration de l'outil."""
        if not self.name or not isinstance(self.name, str):
            raise ValueError("Le nom de l'outil est obligatoire et doit être une chaîne.")

        if not TOOL_NAME_PATTERN.match(self.name):
            raise ValueError(
                f"Nom d'outil invalide: '{self.name}'. Le nom doit comporter entre 3 et 80 caractères "
                "alphanumériques, tirets bas ou traits d'union."
            )

        if not self.description or not isinstance(self.description, str) or len(self.description.strip()) < 5:
            raise ValueError(f"L'outil '{self.name}' doit comporter une description explicite (au moins 5 caractères).")

        if not self.module or not isinstance(self.module, str):
            raise ValueError(f"L'outil '{self.name}' doit spécifier un module propriétaire valide.")

        if not isinstance(self.input_schema, dict):
            raise ValueError(f"Le schéma d'entrée (input_schema) de '{self.name}' doit être un dictionnaire.")

        schema_type = self.input_schema.get("type")
        if schema_type != "object":
            raise ValueError(f"Le schéma input_schema de '{self.name}' doit être de type 'object', obtenu: '{schema_type}'.")

        if "properties" in self.input_schema and not isinstance(self.input_schema["properties"], dict):
            raise ValueError(f"La clé 'properties' de input_schema pour '{self.name}' doit être un dictionnaire.")

        if "required" in self.input_schema and not isinstance(self.input_schema["required"], list):
            raise ValueError(f"La clé 'required' de input_schema pour '{self.name}' doit être une liste.")

        if not self.handler:
            raise ValueError(f"L'outil '{self.name}' doit spécifier un handler (action hook ou fonction callable).")

        if self.timeout_seconds <= 0:
            raise ValueError(f"Le timeout de l'outil '{self.name}' doit être strictement positif.")

    def to_mcp_dict(self) -> dict[str, Any]:
        """Convertit l'outil au format standard exposé au serveur MCP."""
        data: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "module": self.module,
            "version": self.version,
            "enabled": self.enabled,
            "required_permissions": list(self.required_permissions),
            "read_only": self.read_only,
            "destructive": self.destructive,
            "category": self.category,
            "confirmation_required": self.confirmation_required,
            "timeout_seconds": self.timeout_seconds,
            "idempotent": self.idempotent,
        }
        if self.output_schema:
            data["output_schema"] = self.output_schema
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ToolDefinition":
        """Instancie et valide une ToolDefinition depuis un dictionnaire."""
        tool = cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            input_schema=data.get("input_schema", {"type": "object", "properties": {}}),
            module=data.get("module", ""),
            version=data.get("version", "1.0.0"),
            enabled=data.get("enabled", True),
            required_permissions=data.get("required_permissions", []),
            handler=data.get("handler", ""),
            read_only=data.get("read_only", True),
            destructive=data.get("destructive", False),
            category=data.get("category", "general"),
            output_schema=data.get("output_schema"),
            confirmation_required=data.get("confirmation_required", False),
            timeout_seconds=float(data.get("timeout_seconds", 30.0)),
            idempotent=data.get("idempotent", False),
        )
        tool.validate()
        return tool
