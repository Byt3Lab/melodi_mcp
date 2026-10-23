import re
from typing import Any, Optional, Tuple


class ArgumentValidator:
    """Validateur JSON Schema natif sans dépendance externe.

    Valide les arguments fournis à un outil contre son input_schema.
    """

    @classmethod
    def validate(cls, schema: dict[str, Any], data: Any, path: str = "") -> Tuple[bool, Optional[str], Optional[dict[str, Any]]]:
        """Valide 'data' par rapport à 'schema'.

        Retourne (is_valid, error_message, error_details).
        """
        if not isinstance(schema, dict):
            return True, None, None

        expected_type = schema.get("type")

        # 1. Validation du type
        if expected_type is not None:
            type_valid, type_err = cls._check_type(expected_type, data)
            if not type_valid:
                err_path = path or "racine"
                msg = f"Type invalide pour '{err_path}': attendu '{expected_type}', obtenu '{type(data).__name__}'."
                return False, msg, {"path": err_path, "expected": expected_type, "actual": type(data).__name__}

        # 2. Validation enum
        if "enum" in schema and isinstance(schema["enum"], list):
            if data not in schema["enum"]:
                err_path = path or "racine"
                msg = f"Valeur non autorisée pour '{err_path}': '{data}'. Valeurs permises: {schema['enum']}."
                return False, msg, {"path": err_path, "allowed": schema["enum"], "actual": data}

        # 3. Validation chaînes
        if isinstance(data, str):
            if "minLength" in schema and len(data) < schema["minLength"]:
                err_path = path or "racine"
                msg = f"La chaîne '{err_path}' est trop courte (minimum {schema['minLength']} caractères)."
                return False, msg, {"path": err_path, "min_length": schema["minLength"], "actual_length": len(data)}

            if "maxLength" in schema and len(data) > schema["maxLength"]:
                err_path = path or "racine"
                msg = f"La chaîne '{err_path}' est trop longue (maximum {schema['maxLength']} caractères)."
                return False, msg, {"path": err_path, "max_length": schema["maxLength"], "actual_length": len(data)}

            if "pattern" in schema:
                pattern = schema["pattern"]
                if not re.search(pattern, data):
                    err_path = path or "racine"
                    msg = f"La valeur '{err_path}' ne respecte pas le motif regex requis '{pattern}'."
                    return False, msg, {"path": err_path, "pattern": pattern, "actual": data}

        # 4. Validation nombres
        if isinstance(data, (int, float)) and not isinstance(data, bool):
            if "minimum" in schema and data < schema["minimum"]:
                err_path = path or "racine"
                msg = f"La valeur '{err_path}' ({data}) est inférieure au minimum autorisé ({schema['minimum']})."
                return False, msg, {"path": err_path, "minimum": schema["minimum"], "actual": data}

            if "maximum" in schema and data > schema["maximum"]:
                err_path = path or "racine"
                msg = f"La valeur '{err_path}' ({data}) est supérieure au maximum autorisé ({schema['maximum']})."
                return False, msg, {"path": err_path, "maximum": schema["maximum"], "actual": data}

        # 5. Validation objets (dict)
        if isinstance(data, dict):
            # Champs obligatoires
            required_fields = schema.get("required", [])
            for field in required_fields:
                if field not in data:
                    field_path = f"{path}.{field}" if path else field
                    msg = f"Argument obligatoire manquant: '{field_path}'."
                    return False, msg, {"path": field_path, "missing_field": field}

            # Propriétés définies
            properties = schema.get("properties", {})
            additional_allowed = schema.get("additionalProperties", True)

            for key, val in data.items():
                field_path = f"{path}.{key}" if path else key
                if key in properties:
                    prop_schema = properties[key]
                    valid, err_msg, err_det = cls.validate(prop_schema, val, path=field_path)
                    if not valid:
                        return False, err_msg, err_det
                elif additional_allowed is False:
                    msg = f"Propriété non autorisée: '{field_path}'."
                    return False, msg, {"path": field_path, "unexpected_field": key}

        # 6. Validation tableaux (list)
        if isinstance(data, list):
            if "minItems" in schema and len(data) < schema["minItems"]:
                err_path = path or "racine"
                msg = f"Le tableau '{err_path}' contient trop peu d'éléments (minimum {schema['minItems']})."
                return False, msg, {"path": err_path, "min_items": schema["minItems"], "actual": len(data)}

            if "maxItems" in schema and len(data) > schema["maxItems"]:
                err_path = path or "racine"
                msg = f"Le tableau '{err_path}' contient trop d'éléments (maximum {schema['maxItems']})."
                return False, msg, {"path": err_path, "max_items": schema["maxItems"], "actual": len(data)}

            if "items" in schema and isinstance(schema["items"], dict):
                item_schema = schema["items"]
                for idx, item in enumerate(data):
                    item_path = f"{path}[{idx}]"
                    valid, err_msg, err_det = cls.validate(item_schema, item, path=item_path)
                    if not valid:
                        return False, err_msg, err_det

        return True, None, None

    @classmethod
    def _check_type(cls, expected: Any, val: Any) -> Tuple[bool, Optional[str]]:
        if isinstance(expected, list):
            for t in expected:
                ok, _ = cls._check_type(t, val)
                if ok:
                    return True, None
            return False, f"Attend l'un des types {expected}"

        match expected:
            case "string":
                return isinstance(val, str), None
            case "integer":
                # bool is subclass of int in Python, so exclude bool
                return isinstance(val, int) and not isinstance(val, bool), None
            case "number":
                return isinstance(val, (int, float)) and not isinstance(val, bool), None
            case "boolean":
                return isinstance(val, bool), None
            case "array":
                return isinstance(val, list), None
            case "object":
                return isinstance(val, dict), None
            case "null":
                return val is None, None
            case _:
                return True, None
