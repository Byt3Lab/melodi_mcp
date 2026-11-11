// @ts-nocheck
export const ManifestConfigView = {
  delimiters: ['[[', ']]'],
  data() {
    return {
      internalKeyInput: '',
      jwtSecretInput: '',
      serverUrlInput: '',
      serverApiKeyInput: '',
      saving: false,
    };
  },

  computed: {
    config() {
      return this.$store.state.serverConfig;
    },
    internalApiUrl() {
      return this.config.internal_api_url || '/api/melodi_mcp';
    },
    manifestJson() {
      return this.config.manifest_json || '{}';
    },
    catalogRevision() {
      return this.config.catalog_revision || '00000000';
    },
    contractVersion() {
      return this.config.contract_version || '1.0.0';
    },
  },

  methods: {
    syncInputsFromConfig() {
      if (this.config) {
        this.internalKeyInput = this.config.internal_key || '';
        this.jwtSecretInput = this.config.jwt_secret || '';
        this.serverUrlInput = this.config.mcp_server_url || '';
        this.serverApiKeyInput = this.config.mcp_server_api_key || '';
      }
    },

    async generateKey(type) {
      const generated = await this.$store.dispatch('generateServerKey', type);
      if (generated) {
        if (type === 'internal_key') {
          this.internalKeyInput = generated;
        } else if (type === 'jwt_secret') {
          this.jwtSecretInput = generated;
        }
        this.$store.dispatch('showToast', {
          message: `Nouvelle valeur générée pour ${type}. Cliquez sur Enregistrer pour confirmer.`,
          type: 'info',
        });
      }
    },

    async saveInternalKey() {
      this.saving = true;
      try {
        await this.$store.dispatch('updateServerConfig', {
          internal_key: this.internalKeyInput,
        });
      } finally {
        this.saving = false;
      }
    },

    async saveJwtSecret() {
      this.saving = true;
      try {
        await this.$store.dispatch('updateServerConfig', {
          jwt_secret: this.jwtSecretInput,
        });
      } finally {
        this.saving = false;
      }
    },

    async saveServerConnection() {
      this.saving = true;
      try {
        await this.$store.dispatch('updateServerConfig', {
          mcp_server_url: this.serverUrlInput,
          mcp_server_api_key: this.serverApiKeyInput,
        });
      } finally {
        this.saving = false;
      }
    },

    copyManifest() {
      navigator.clipboard.writeText(this.manifestJson).then(() => {
        this.$store.dispatch('showToast', {
          message: 'Manifeste JSON copié dans le presse-papier !',
          type: 'success',
        });
      });
    },

    copyInternalApiUrl() {
      navigator.clipboard.writeText(this.internalApiUrl).then(() => {
        this.$store.dispatch('showToast', {
          message: 'URL d\'API copiée dans le presse-papier !',
          type: 'success',
        });
      });
    },
  },

  async mounted() {
    this.$store.commit('SET_ACTIVE_TAB', 'manifest');
    const cfg = await this.$store.dispatch('fetchServerConfig');
    if (cfg) {
      this.syncInputsFromConfig();
    }
  },

  template: { el: '#tpl-mcp-manifest' },
};
