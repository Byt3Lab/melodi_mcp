// @ts-nocheck
export const ServerSupervisorView = {
  delimiters: ['[[', ']]'],
  computed: {
    status() {
      return this.$store.state.serverStatus;
    },
    isOnline() {
      return Boolean(this.status.is_online);
    },
    latencyMs() {
      return this.status.latency_ms || 0;
    },
    latencyClass() {
      const ms = this.latencyMs;
      if (!this.isOnline) return 'slow';
      if (ms < 60) return 'fast';
      if (ms < 180) return 'medium';
      return 'slow';
    },
    serverToolsCount() {
      return this.status.server_tools_count || 0;
    },
    totalErpTools() {
      return this.status.total_erp_tools || 0;
    },
    serverRevision() {
      return this.status.server_revision || this.status.catalog_revision || '-';
    },
    catalogRevision() {
      return this.status.catalog_revision || '-';
    },
    uptime() {
      return this.status.server_uptime || '-';
    },
    version() {
      return this.status.server_version || '0.1.0';
    },
    mcpServerUrl() {
      return this.status.mcp_server_url || 'http://localhost:8765/mcp';
    },
    serverBaseUrl() {
      return this.status.server_base_url || 'http://localhost:8765';
    },
    isPinging() {
      return this.$store.state.serverPinging;
    },
    isSyncing() {
      return this.$store.state.serverSyncing;
    },
    clientSnippet() {
      const url = this.mcpServerUrl;
      return JSON.stringify({
        mcpServers: {
          melodi: {
            type: "http",
            url: url,
            headers: {
              Authorization: "Bearer <VOTRE_TOKEN_MCP>"
            }
          }
        }
      }, null, 2);
    },
  },

  methods: {
    onPing() {
      this.$store.dispatch('pingServer');
    },
    onSync() {
      this.$store.dispatch('syncServer');
    },
    copyClientSnippet() {
      navigator.clipboard.writeText(this.clientSnippet).then(() => {
        this.$store.dispatch('showToast', {
          message: 'Configuration JSON copiée dans le presse-papier !',
          type: 'success',
        });
      });
    },
    goToTokens() {
      this.$router.push('/tokens');
    },
    goToManifest() {
      this.$router.push('/manifest');
    },
  },

  mounted() {
    this.$store.commit('SET_ACTIVE_TAB', 'server');
    this.$store.dispatch('fetchServerStatus');
  },

  template: { el: '#tpl-mcp-server' },
};
