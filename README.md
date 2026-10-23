# MELODI MCP (`melodi_mcp`)

Le module **`melodi_mcp`** est le composant interne officiel de MELODI ERP permettant aux modules métier d'exposer des outils et des capacités structurées exploitables par des assistants d'intelligence artificielle via le protocole MCP (*Model Context Protocol*).

---

## 1. Séparation des responsabilités : `melodi_mcp` vs `melodi_mcp_server`

Il est capital de distinguer deux briques distinctes :

```
┌─────────────────────────────────┐
│     Client IA (Claude, etc.)    │
└────────────────┬────────────────┘
                 │ Protocole MCP (stdio / SSE / JSON-RPC)
                 ▼
┌─────────────────────────────────┐
│        melodi_mcp_server        │  (Application externe indépendante)
└────────────────┬────────────────┘
                 │ HTTP REST + JSON + Auth (JWT / Service Key)
                 ▼
┌─────────────────────────────────┐
│           melodi_mcp            │  (Ce module MELODI ERP)
│  - Registre centralisé d'outils │
│  - Validation des arguments     │
│  - Contrôle RBAC & contextuel   │
│  - Exécution des capacités ERP  │
│  - Journal d'audit sécurisé     │
│  - Révision ETag du catalogue   │
└─────────────────────────────────┘
```

- **`melodi_mcp` (ce module)** :
  - Définit le contrat technique des outils (nom, schéma JSON, permissions, timeout, flags).
  - Maintient le registre en mémoire et gère les révisions du catalogue (`catalog_revision` SHA-256).
  - Valide rigoureusement les arguments reçus contre le schéma JSON de chaque outil.
  - Vérifie les autorisations de l'utilisateur (RBAC) et l'état des modules propriétaires.
  - Exécute les fonctionnalités métier via le `HookManager` ou des handlers asynchrones.
  - Enregistre les métadonnées d'exécution dans le journal d'audit sans fuite de secrets.
  - N'implémente **aucun transport MCP externe** (pas de SSE ni de flux stdio pour les LLM).

- **`melodi_mcp_server` (application externe)** :
  - Implémente le protocole MCP officiel (transports stdio / SSE).
  - Dialogue avec les clients IA externes.
  - Découvre les outils et délègue leur exécution à `melodi_mcp` via l'API interne sécurisée.

---

## 2. Déclaration d'outils par les modules métier

Un module métier peut déclarer ses outils au moment de son initialisation (`load()`) sans jamais créer de couplage dur avec `melodi_mcp`.

### 2.1 Spécification d'un outil

Chaque outil expose :
- `name` : identifiant technique unique (format `^[a-zA-Z0-9_\-\.]{3,80}$`).
- `description` : texte explicatif clair et contextuel pour guider le raisonnement du LLM.
- `input_schema` : schéma standard JSON Schema de type `"object"` avec ses `properties` et `required`.
- `module` : identifiant du module propriétaire (ex: `"melodi_wallet"`, `"melodi_invoicing"`).
- `version` : version sémantique du contrat (ex: `"1.0.0"`).
- `enabled` : booléen d'activation.
- `required_permissions` : liste des permissions RBAC nécessaires (ex: `["wallet:read"]`).
- `handler` : référence d'action `"{module}:{action_name}"` ou fonction callable asynchrone.
- `read_only` : `True` s'il s'agit d'une simple consultation sans écriture.
- `destructive` : `True` si l'opération entraîne une suppression ou une modification difficilement réversible.
- `confirmation_required` : `True` si l'exécution requiert le flag `confirmed: true`.
- `timeout_seconds` : durée maximale d'exécution autorisée (défaut : 30.0s).

---

### 2.2 Exemple 1 : Déclaration d'un outil de lecture (Ex: Consultation de solde)

Dans le module `melodi_wallet/module.py` :

```python
async def load(self):
    # 1. Enregistrement de l'action métier normale dans HookManager
    self.add_action("get_wallet_balance", self.action_get_wallet_balance)

    # 2. Déclaration de l'outil auprès de melodi_mcp via la zone 'mcp_tools' du Registry
    self.register_contribution("mcp_tools", {
        "name": "wallet_get_balance",
        "description": "Consulte le solde disponible et la devise d'un portefeuille numérique.",
        "module": "melodi_wallet",
        "category": "finance",
        "version": "1.0.0",
        "read_only": True,
        "destructive": False,
        "required_permissions": ["wallet:read"],
        "handler": "melodi_wallet:get_wallet_balance",
        "input_schema": {
            "type": "object",
            "properties": {
                "wallet_id": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Identifiant numérique du portefeuille."
                }
            },
            "required": ["wallet_id"],
            "additionalProperties": False
        }
    })
```

---

### 2.3 Exemple 2 : Déclaration d'un outil d'écriture sensible (Ex: Création de facture)

Dans le module `melodi_invoicing/module.py` :

```python
async def load(self):
    # 1. Action métier transactionnelle
    self.add_action("create_invoice", self.action_create_invoice)

    # 2. Déclaration de l'outil avec confirmation requise
    self.register_contribution("mcp_tools", {
        "name": "invoicing_create_invoice",
        "description": "Crée une nouvelle facture client dans MELODI ERP.",
        "module": "melodi_invoicing",
        "category": "billing",
        "version": "1.0.0",
        "read_only": False,
        "destructive": False,
        "confirmation_required": True,  # L'assistant doit explicitement demander validation
        "required_permissions": ["invoicing:create"],
        "handler": "melodi_invoicing:create_invoice",
        "input_schema": {
            "type": "object",
            "properties": {
                "contact_id": {
                    "type": "string",
                    "description": "Identifiant du contact client."
                },
                "lines": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "description": {"type": "string", "minLength": 2},
                            "quantity": {"type": "number", "minimum": 0.01},
                            "unit_price": {"type": "number", "minimum": 0}
                        },
                        "required": ["description", "quantity", "unit_price"]
                    }
                }
            },
            "required": ["contact_id", "lines"]
        }
    })
```

> **Note sur le cycle de vie** : Lorsque le module `melodi_wallet` ou `melodi_invoicing` est désactivé via le gestionnaire de modules, le `Registry` central désenregistre automatiquement ses outils, et `melodi_mcp` actualise immédiatement la révision de son catalogue.

---

## 3. Contrat de l'API REST Interne

Toutes les routes sont préfixées par `/api/melodi_mcp/` :

| Méthode | Route | Description |
|---|---|---|
| `GET` | `/api/melodi_mcp/internal/health` | Vérifie l'état de santé du module et du registre. |
| `GET` | `/api/melodi_mcp/internal/manifest` | Expose les métadonnées, révisions et capacités supportées. |
| `GET` | `/api/melodi_mcp/internal/revision` | Retourne la révision du catalogue (supporte `If-None-Match` -> `304`). |
| `GET` | `/api/melodi_mcp/internal/tools` | Découvre le catalogue filtrable (`module`, `category`, `read_only`). |
| `POST` | `/api/melodi_mcp/internal/tools/<name>/execute` | Exécute un outil avec arguments et contrôle d'accès. |
| `POST` | `/api/melodi_mcp/internal/tools/execute` | Alias d'exécution avec nom d'outil dans query ou body. |
| `GET` | `/api/melodi_mcp/internal/audit-logs` | Consulte les journaux d'audit des exécutions. |

---

### 3.1 Authentification

Les requêtes vers les endpoints protégés (`tools`, `execute`, `audit-logs`) doivent fournir l'un des mécanismes suivants :

1. **Jeton Bearer JWT utilisateur** :
   ```http
   Authorization: Bearer <jwt_token>
   ```
   L'identité et les permissions de l'utilisateur sont extraites et validées en temps réel par MELODI.

2. **Jeton de service interne partagé** :
   ```http
   X-Internal-MCP-Key: <MELODI_MCP_INTERNAL_KEY>
   ```
   Ou :
   ```http
   Authorization: Bearer <MELODI_MCP_INTERNAL_KEY>
   ```
   Peut être complété par l'en-tête `X-MCP-User-Token: <user_jwt>` pour propager le contexte sécurisé d'un utilisateur sans usurpation possible.

---

### 3.2 Format des Requêtes d'Exécution

```http
POST /api/melodi_mcp/internal/tools/wallet_get_balance/execute
Content-Type: application/json
Authorization: Bearer <jwt_token>

{
  "arguments": {
    "wallet_id": 42
  },
  "correlation_id": "corr-uuid-9876",
  "confirmed": false,
  "context": {
    "branch_id": "agency_paris"
  }
}
```

---

### 3.3 Format des Réponses

#### Succès (HTTP 200) :
```json
{
  "success": true,
  "correlation_id": "corr-uuid-9876",
  "data": {
    "result": {
      "status": "success",
      "balance": "1500.00",
      "currency": "EUR"
    },
    "metadata": {
      "tool": "wallet_get_balance",
      "module": "melodi_wallet",
      "duration_ms": 11.45,
      "timestamp": "2026-10-23T06:50:00Z"
    }
  }
}
```

#### Erreur (HTTP 400 / 401 / 403 / 404 / 422 / 503 / 504) :
```json
{
  "success": false,
  "correlation_id": "corr-uuid-9876",
  "error": {
    "code": "INVALID_ARGUMENTS",
    "message": "Type invalide pour 'wallet_id': attendu 'integer', obtenu 'str'.",
    "details": {
      "path": "wallet_id",
      "expected": "integer",
      "actual": "str"
    }
  }
}
```

---

## 4. Codes d'Erreurs Normalisés

| Code d'erreur | HTTP Status | Signification |
|---|---|---|
| `AUTHENTICATION_REQUIRED` | 401 | Jeton manquant, expiré ou invalide. |
| `PERMISSION_DENIED` | 403 | L'utilisateur n'a pas les permissions requises pour l'outil. |
| `TOOL_NOT_FOUND` | 404 | L'outil spécifié n'existe pas dans le registre. |
| `TOOL_DISABLED` | 400 | L'outil a été désactivé par l'administrateur. |
| `MODULE_UNAVAILABLE` | 503 | Le module propriétaire de l'outil est inactif ou désinstallé. |
| `INVALID_ARGUMENTS` | 422 | Arguments non conformes au schéma JSON de l'outil. |
| `CONFIRMATION_REQUIRED` | 400 | Outil sensible nécessitant confirmation (`confirmed: true`). |
| `CONTRACT_VERSION_CONFLICT` | 409 | Version de contrat incompatible. |
| `EXECUTION_TIMEOUT` | 504 | Délai maximal d'exécution dépassé. |
| `BUSINESS_ERROR` | 400 | Exception métier levée par le service. |
| `INTERNAL_ERROR` | 500 | Erreur interne non gérée. |

---

## 5. Journalisation et Audit

Chaque exécution d'outil est enregistrée dans la table SQL `melodi_mcp_audit_logs`.
Pour des raisons strictes de sécurité et de confidentialité :
- Les arguments complets et les données personnelles / financières ne sont **pas stockés en clair**.
- Seules les métadonnées sont journalisées : `correlation_id`, `tool_name`, `module_name`, `user_id`, `branch_id`, `status`, `error_code`, `duration_ms`, `created_at`.

---

## 6. Procédure de Test

Exécutez la suite complète de tests unitaires et d'intégration :

```bash
venv/bin/pytest tests/test_melodi_mcp.py -v
```
