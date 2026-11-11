// @ts-nocheck
export const UserTokensView = {
  delimiters: ['[[', ']]'],
  data() {
    return {
      agentName: '',
      expiresInHours: 24,
      tokenToDelete: null,
      showDeleteModal: false,
      creating: false,
    };
  },

  computed: {
    userContext() {
      return this.$store.state.userContext;
    },
    currentUsername() {
      return this.userContext.username || this.userContext.user_id || 'Utilisateur';
    },
    isSudo() {
      return Boolean(this.userContext.is_sudo);
    },
    permissions() {
      return this.userContext.permissions || [];
    },
    tokens() {
      return this.$store.state.tokens || [];
    },
    newlyCreatedToken() {
      return this.$store.state.newlyCreatedToken;
    },
    mcpServerUrl() {
      return this.$store.state.serverStatus.mcp_server_url || 'http://localhost:8765/mcp';
    },
    mcpConfigSnippet() {
      const tokenVal = this.newlyCreatedToken || '<VOTRE_TOKEN_MCP>';
      return JSON.stringify({
        mcpServers: {
          melodi: {
            url: this.mcpServerUrl,
            type: "http",
            headers: {
              Authorization: `Bearer ${tokenVal}`
            }
          }
        }
      }, null, 2);
    },
  },

  methods: {
    async handleCreateToken() {
      const name = (this.agentName || '').trim() || `Agent IA - ${this.currentUsername}`;
      this.creating = true;
      try {
        await this.$store.dispatch('createToken', {
          name: name,
          expires_in_hours: parseInt(this.expiresInHours, 10) || 24,
        });
        this.agentName = '';
      } finally {
        this.creating = false;
      }
    },

    copyNewToken() {
      if (!this.newlyCreatedToken) return;
      navigator.clipboard.writeText(this.newlyCreatedToken).then(() => {
        this.$store.dispatch('showToast', {
          message: 'Token personnel copié dans le presse-papier !',
          type: 'success',
        });
      });
    },

    copyMcpConfig() {
      navigator.clipboard.writeText(this.mcpConfigSnippet).then(() => {
        this.$store.dispatch('showToast', {
          message: 'Configuration MCP copiée dans le presse-papier !',
          type: 'success',
        });
      });
    },

    async handleToggleToken(token) {
      if (!token) return;
      await this.$store.dispatch('toggleToken', token.id);
    },

    confirmDelete(token) {
      this.tokenToDelete = token;
      this.showDeleteModal = true;
    },

    cancelDelete() {
      this.tokenToDelete = null;
      this.showDeleteModal = false;
    },

    async executeDelete() {
      if (!this.tokenToDelete) return;
      const id = this.tokenToDelete.id;
      const success = await this.$store.dispatch('deleteToken', id);
      if (success) {
        this.cancelDelete();
      }
    },
  },

  mounted() {
    this.$store.commit('SET_ACTIVE_TAB', 'tokens');
    this.$store.dispatch('fetchUserContext');
    this.$store.dispatch('fetchTokens');
    this.$store.dispatch('fetchServerStatus');
  },

  template: { el: '#tpl-mcp-tokens' },
};
