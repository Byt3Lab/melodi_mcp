import os
from core import get_prefix_table
from core.db.base_module_tables import BaseModuleTables

MODULE_NAME = "melodi_mcp"
PREFIX_TABLE = get_prefix_table(MODULE_NAME)

class MCPTables(BaseModuleTables):
    """Centralisation des tables SQL du module melodi_mcp."""
    AUDIT_LOGS = f"{PREFIX_TABLE}audit_logs"


CONTRACT_VERSION = "1.0.0"
DEFAULT_TIMEOUT_SECONDS = 30.0
MCP_INTERNAL_KEY = os.environ.get("MELODI_MCP_INTERNAL_KEY", "mcp-internal-secret-token")
