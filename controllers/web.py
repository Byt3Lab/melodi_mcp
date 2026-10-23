from core.page_builder import Page, Component
from core.routing import Request, Response
from base.components import admin_layout
from ..services.tool_registry import ToolRegistry
from ..services.auditor import MCPAuditor
from ..config import CONTRACT_VERSION


class MCPWebController:
    """Contrôleur Web d'administration pour melodi_mcp."""

    @staticmethod
    async def admin_dashboard(request: Request, response: Response):
        """Page principale d'administration et vue d'ensemble du catalogue MCP."""
        registry = ToolRegistry.get_instance(app=request.app)
        auditor = MCPAuditor(app=request.app)

        tools = registry.list_tools(enabled_only=False, check_module_active=False)
        active_tools = [t for t in tools if t.enabled and registry.is_module_active(t.module)]
        recent_logs = await auditor.list_recent_executions(limit=30)

        tools_data = []
        for t in tools:
            td = t.to_mcp_dict()
            td["is_active"] = t.enabled and registry.is_module_active(t.module)
            tools_data.append(td)

        content = Component(module_name="melodi_mcp", name="dashboard", context={
            "tools": tools_data,
            "active_tools_count": len(active_tools),
            "total_tools_count": len(tools),
            "catalog_revision": registry.get_revision(),
            "contract_version": CONTRACT_VERSION,
            "recent_logs": recent_logs,
        })

        page = Page("MELODI MCP", admin_layout(content))
        return await response.render_page(page)
