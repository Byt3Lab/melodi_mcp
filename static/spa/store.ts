// @ts-nocheck
import { MelodiStore } from '/static/base/melodiJS/index.js';

export const store = new MelodiStore({
  state() {
    return {
      activeTab: 'catalog',
      loading: false,
      serverPinging: false,
      serverSyncing: false,
      toast: null,

      // Synthèse & KPIs
      overview: {
        active_tools_count: 0,
        total_tools_count: 0,
        catalog_revision: '00000000',
        contract_version: '1.0.0',
        recent_logs: [],
        server_url: '',
      },

      // Catalogue
      tools: [],
      catalogRevision: '',
      toolsFilter: {
        query: '',
        category: '',
        module: '',
        type: '', // all, read_only, write, destructive
      },

      // Supervision Serveur
      serverStatus: {
        is_online: false,
        latency_ms: 0,
        server_status: 'UNKNOWN',
        server_tools_count: 0,
        total_erp_tools: 0,
        catalog_revision: '',
        server_revision: '',
        server_uptime: '-',
        server_version: '0.1.0',
        error_detail: null,
        mcp_server_url: 'http://localhost:8765/mcp',
        server_base_url: 'http://localhost:8765',
        jwt_secret_set: false,
        mcp_api_key_set: false,
      },

      // Utilisateur & Tokens
      userContext: {
        user_id: '',
        username: '',
        is_sudo: false,
        permissions: [],
      },
      tokens: [],
      newlyCreatedToken: null,

      // Audit
      auditLogs: [],
      availableTools: [],
      auditFilter: {
        tool: '',
        status: '',
        limit: 50,
      },

      // Manifeste & Paramètres
      serverConfig: {
        internal_key: '',
        jwt_secret: '',
        mcp_server_url: '',
        mcp_server_api_key: '',
        internal_api_url: '',
        contract_version: '',
        catalog_revision: '',
        manifest_json: '',
      },
    };
  },

  mutations: {
    SET_ACTIVE_TAB(state, tab) {
      state.activeTab = tab;
    },
    SET_LOADING(state, val) {
      state.loading = Boolean(val);
    },
    SET_SERVER_PINGING(state, val) {
      state.serverPinging = Boolean(val);
    },
    SET_SERVER_SYNCING(state, val) {
      state.serverSyncing = Boolean(val);
    },
    SET_TOAST(state, toast) {
      state.toast = toast;
    },
    CLEAR_TOAST(state) {
      state.toast = null;
    },
    SET_OVERVIEW(state, data) {
      if (data) {
        state.overview = Object.assign({}, state.overview, data);
        if (data.catalog_revision) state.catalogRevision = data.catalog_revision;
      }
    },
    SET_TOOLS(state, payload) {
      if (Array.isArray(payload)) {
        state.tools = payload;
      } else if (payload && Array.isArray(payload.tools)) {
        state.tools = payload.tools;
      }
    },
    SET_TOOLS_FILTER(state, filters) {
      state.toolsFilter = Object.assign({}, state.toolsFilter, filters);
    },
    SET_SERVER_STATUS(state, data) {
      if (data) {
        state.serverStatus = Object.assign({}, state.serverStatus, data);
      }
    },
    SET_USER_CONTEXT(state, user) {
      if (user) {
        state.userContext = Object.assign({}, state.userContext, user);
      }
    },
    SET_TOKENS(state, tokens) {
      state.tokens = Array.isArray(tokens) ? tokens : [];
    },
    SET_NEWLY_CREATED_TOKEN(state, token) {
      state.newlyCreatedToken = token;
    },
    SET_AUDIT_LOGS(state, payload) {
      if (payload && Array.isArray(payload.data)) {
        state.auditLogs = payload.data;
        if (payload.meta && Array.isArray(payload.meta.available_tools)) {
          state.availableTools = payload.meta.available_tools;
        }
      } else if (Array.isArray(payload)) {
        state.auditLogs = payload;
      }
    },
    SET_AUDIT_FILTER(state, filters) {
      state.auditFilter = Object.assign({}, state.auditFilter, filters);
    },
    SET_SERVER_CONFIG(state, config) {
      if (config) {
        state.serverConfig = Object.assign({}, state.serverConfig, config);
      }
    },
  },

  actions: {
    showToast({ commit }, { message, type = 'info', duration = 4000 }) {
      commit('SET_TOAST', { message, type });
      setTimeout(() => {
        commit('CLEAR_TOAST');
      }, duration);
    },

    async fetchOverview({ commit }) {
      try {
        const res = await window.melodi.api.get('/api/melodi_mcp/overview');
        if (res && res.success && res.data) {
          commit('SET_OVERVIEW', res.data);
        }
      } catch (err) {
        console.error('[melodi_mcp] Erreur chargement aperçu:', err);
      }
    },

    async fetchTools({ commit }) {
      try {
        const res = await window.melodi.api.get('/api/melodi_mcp/tools');
        if (res && res.success && res.data) {
          commit('SET_TOOLS', res.data.tools || []);
          if (res.catalog_revision) {
            commit('SET_OVERVIEW', { catalog_revision: res.catalog_revision });
          }
        }
      } catch (err) {
        console.error('[melodi_mcp] Erreur chargement outils:', err);
      }
    },

    async fetchServerStatus({ commit }) {
      try {
        const res = await window.melodi.api.get('/api/melodi_mcp/server/status');
        if (res && res.success && res.data) {
          commit('SET_SERVER_STATUS', res.data);
          return res.data;
        }
      } catch (err) {
        console.error('[melodi_mcp] Erreur statut serveur:', err);
      }
      return null;
    },

    async pingServer({ commit, dispatch }) {
      commit('SET_SERVER_PINGING', true);
      try {
        const data = await dispatch('fetchServerStatus');
        if (data && data.is_online) {
          dispatch('showToast', {
            message: `Connexion établie avec le serveur MCP (${data.latency_ms} ms) !`,
            type: 'success',
          });
        } else {
          dispatch('showToast', {
            message: `Impossible de contacter le serveur MCP : ${data ? data.error_detail : 'Hors ligne'}`,
            type: 'danger',
          });
        }
      } finally {
        commit('SET_SERVER_PINGING', false);
      }
    },

    async syncServer({ commit, dispatch }) {
      commit('SET_SERVER_SYNCING', true);
      try {
        const res = await window.melodi.api.post('/api/melodi_mcp/server/sync', {});
        if (res && res.success) {
          dispatch('showToast', {
            message: res.message || 'Catalogue resynchronisé sur le serveur MCP avec succès !',
            type: 'success',
          });
          dispatch('fetchServerStatus');
        } else {
          dispatch('showToast', {
            message: (res && res.error ? res.error.message : 'Erreur de resynchronisation.'),
            type: 'warning',
          });
        }
      } catch (err) {
        dispatch('showToast', {
          message: `Échec appel synchronisation : ${err.message || err}`,
          type: 'danger',
        });
      } finally {
        commit('SET_SERVER_SYNCING', false);
      }
    },

    async fetchUserContext({ commit }) {
      try {
        const res = await window.melodi.api.get('/api/melodi_mcp/me');
        if (res && res.success && res.data) {
          commit('SET_USER_CONTEXT', res.data);
        }
      } catch (err) {
        console.error('[melodi_mcp] Erreur chargement contexte utilisateur:', err);
      }
    },

    async fetchTokens({ commit }) {
      try {
        const res = await window.melodi.api.get('/api/melodi_mcp/tokens');
        if (res && res.success && res.data) {
          commit('SET_TOKENS', res.data);
        }
      } catch (err) {
        console.error('[melodi_mcp] Erreur chargement tokens:', err);
      }
    },

    async createToken({ commit, dispatch }, payload) {
      try {
        const res = await window.melodi.api.post('/api/melodi_mcp/tokens', payload);
        if (res && res.success && res.data) {
          commit('SET_NEWLY_CREATED_TOKEN', res.data.token || res.data.raw_key);
          dispatch('fetchTokens');
          dispatch('showToast', {
            message: 'Jeton personnel MCP généré avec succès !',
            type: 'success',
          });
          return res.data;
        }
      } catch (err) {
        dispatch('showToast', {
          message: `Erreur création jeton : ${err.message || err}`,
          type: 'danger',
        });
      }
      return null;
    },

    async toggleToken({ dispatch }, tokenId) {
      try {
        const res = await window.melodi.api.post(`/api/melodi_mcp/tokens/${tokenId}/toggle`, {});
        if (res && res.success) {
          dispatch('showToast', {
            message: res.message || 'Statut du jeton mis à jour.',
            type: 'info',
          });
          dispatch('fetchTokens');
          return true;
        }
      } catch (err) {
        dispatch('showToast', {
          message: `Erreur bascule statut : ${err.message || err}`,
          type: 'danger',
        });
      }
      return false;
    },

    async deleteToken({ dispatch }, tokenId) {
      try {
        const res = await window.melodi.api.delete(`/api/melodi_mcp/tokens/${tokenId}`);
        if (res && res.success) {
          dispatch('showToast', {
            message: 'Jeton révoqué et supprimé définitivement.',
            type: 'warning',
          });
          dispatch('fetchTokens');
          return true;
        }
      } catch (err) {
        dispatch('showToast', {
          message: `Erreur suppression jeton : ${err.message || err}`,
          type: 'danger',
        });
      }
      return false;
    },

    async fetchAuditLogs({ commit, state }, customFilters) {
      const filters = Object.assign({}, state.auditFilter, customFilters || {});
      commit('SET_AUDIT_FILTER', filters);

      let queryParams = [];
      if (filters.tool) queryParams.push(`tool_name=${encodeURIComponent(filters.tool)}`);
      if (filters.status) queryParams.push(`status=${encodeURIComponent(filters.status)}`);
      if (filters.limit) queryParams.push(`limit=${encodeURIComponent(filters.limit)}`);

      const url = `/api/melodi_mcp/audit-logs${queryParams.length ? '?' + queryParams.join('&') : ''}`;
      try {
        const res = await window.melodi.api.get(url);
        if (res && res.success) {
          commit('SET_AUDIT_LOGS', res);
        }
      } catch (err) {
        console.error('[melodi_mcp] Erreur chargement audit:', err);
      }
    },

    async fetchServerConfig({ commit }) {
      try {
        const res = await window.melodi.api.get('/api/melodi_mcp/server/config');
        if (res && res.success && res.data) {
          commit('SET_SERVER_CONFIG', res.data);
          return res.data;
        }
      } catch (err) {
        console.error('[melodi_mcp] Erreur chargement config serveur:', err);
      }
      return null;
    },

    async updateServerConfig({ dispatch }, payload) {
      try {
        const res = await window.melodi.api.post('/api/melodi_mcp/server/config', payload);
        if (res && res.success) {
          dispatch('showToast', {
            message: res.message || 'Paramètres serveur sauvegardés avec succès !',
            type: 'success',
          });
          dispatch('fetchServerConfig');
          dispatch('fetchServerStatus');
          return true;
        }
      } catch (err) {
        dispatch('showToast', {
          message: `Erreur mise à jour configuration : ${err.message || err}`,
          type: 'danger',
        });
      }
      return false;
    },

    async generateServerKey({ dispatch }, keyType) {
      try {
        const res = await window.melodi.api.post('/api/melodi_mcp/server/config/generate', { type: keyType });
        if (res && res.success && res.data) {
          return res.data.generated_key;
        }
      } catch (err) {
        dispatch('showToast', {
          message: `Erreur génération clé : ${err.message || err}`,
          type: 'danger',
        });
      }
      return '';
    },
  },
});
