// @ts-nocheck
import { MelodiRouter } from '/static/base/melodiJS/index.js';
import { ToolsCatalogView } from './views/ToolsCatalogView.js';
import { ServerSupervisorView } from './views/ServerSupervisorView.js';
import { UserTokensView } from './views/UserTokensView.js';
import { AuditLogsView } from './views/AuditLogsView.js';
import { ManifestConfigView } from './views/ManifestConfigView.js';

export const router = new MelodiRouter({
  mode: 'hash',
  routes: [
    {
      path: '/',
      name: 'mcp-catalog',
      component: ToolsCatalogView,
    },
    {
      path: '/catalog',
      name: 'mcp-catalog-alias',
      component: ToolsCatalogView,
    },
    {
      path: '/server',
      name: 'mcp-server',
      component: ServerSupervisorView,
    },
    {
      path: '/tokens',
      name: 'mcp-tokens',
      component: UserTokensView,
    },
    {
      path: '/audit',
      name: 'mcp-audit',
      component: AuditLogsView,
    },
    {
      path: '/manifest',
      name: 'mcp-manifest',
      component: ManifestConfigView,
    },
  ],
});
