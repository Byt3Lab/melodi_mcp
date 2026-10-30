import os
from core import get_prefix_table
from core.db.base_module_tables import BaseModuleTables

MODULE_NAME = "melodi_mcp"
PREFIX_TABLE = get_prefix_table(MODULE_NAME)

class MCPTables(BaseModuleTables):
    """Centralisation des tables SQL du module melodi_mcp."""
    AUDIT_LOGS = f"{PREFIX_TABLE}audit_logs"
    API_KEYS = f"{PREFIX_TABLE}api_keys"


CONTRACT_VERSION = "1.0.0"
DEFAULT_TIMEOUT_SECONDS = 30.0
MCP_INTERNAL_KEY = os.environ.get("MELODI_MCP_INTERNAL_KEY", "mcp-internal-secret-token")
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:8765/mcp")
MCP_SERVER_API_KEY = os.environ.get("MCP_API_KEY", "mon-super-token-mcp-securise-2026")
