// @ts-nocheck
export const AuditLogsView = {
  delimiters: ['[[', ']]'],
  data() {
    return {
      selectedTool: '',
      selectedStatus: '',
      searchQuery: '',
      selectedLogDetail: null,
      showDetailModal: false,
    };
  },

  computed: {
    logs() {
      return this.$store.state.auditLogs || [];
    },
    availableTools() {
      return this.$store.state.availableTools || [];
    },
    filteredLogs() {
      let list = this.logs;
      const q = (this.searchQuery || '').trim().toLowerCase();
      if (q) {
        list = list.filter((l) => {
          const tn = (l.tool_name || '').toLowerCase();
          const cid = (l.correlation_id || '').toLowerCase();
          const uid = (l.user_id || '').toLowerCase();
          const mod = (l.module_name || '').toLowerCase();
          return tn.includes(q) || cid.includes(q) || uid.includes(q) || mod.includes(q);
        });
      }
      return list;
    },
  },

  methods: {
    onFilterChange() {
      this.$store.dispatch('fetchAuditLogs', {
        tool: this.selectedTool,
        status: this.selectedStatus,
      });
    },

    resetFilters() {
      this.selectedTool = '';
      this.selectedStatus = '';
      this.searchQuery = '';
      this.$store.dispatch('fetchAuditLogs', { tool: '', status: '' });
    },

    openDetailModal(log) {
      this.selectedLogDetail = log;
      this.showDetailModal = true;
    },

    closeDetailModal() {
      this.selectedLogDetail = null;
      this.showDetailModal = false;
    },
  },

  mounted() {
    this.$store.commit('SET_ACTIVE_TAB', 'audit');
    this.$store.dispatch('fetchAuditLogs');
  },

  template: { el: '#tpl-mcp-audit' },
};
