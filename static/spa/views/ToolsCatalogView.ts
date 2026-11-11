// @ts-nocheck
export const ToolsCatalogView = {
  delimiters: ['[[', ']]'],
  data() {
    return {
      searchQuery: '',
      selectedCategory: '',
      selectedModule: '',
      selectedType: '',
      viewMode: 'table',
      selectedToolForSchema: null,
      showSchemaModal: false,
    };
  },

  computed: {
    overview() {
      return this.$store.state.overview;
    },
    tools() {
      return this.$store.state.tools || [];
    },
    activeToolsCount() {
      return this.overview.active_tools_count || this.tools.length;
    },
    totalToolsCount() {
      return this.overview.total_tools_count || this.tools.length;
    },
    catalogRevision() {
      return this.overview.catalog_revision || '00000000';
    },
    contractVersion() {
      return this.overview.contract_version || '1.0.0';
    },
    categories() {
      const cats = new Set();
      this.tools.forEach((t) => {
        if (t.category) cats.add(t.category);
      });
      return Array.from(cats).sort();
    },
    modules() {
      const mods = new Set();
      this.tools.forEach((t) => {
        if (t.module) mods.add(t.module);
      });
      return Array.from(mods).sort();
    },
    filteredTools() {
      let list = this.tools;
      const q = (this.searchQuery || '').trim().toLowerCase();

      if (q) {
        list = list.filter((t) => {
          const name = (t.name || '').toLowerCase();
          const desc = (t.description || '').toLowerCase();
          const mod = (t.module || '').toLowerCase();
          const cat = (t.category || '').toLowerCase();
          return name.includes(q) || desc.includes(q) || mod.includes(q) || cat.includes(q);
        });
      }

      if (this.selectedCategory) {
        list = list.filter((t) => t.category === this.selectedCategory);
      }

      if (this.selectedModule) {
        list = list.filter((t) => t.module === this.selectedModule);
      }

      if (this.selectedType === 'read_only') {
        list = list.filter((t) => t.read_only);
      } else if (this.selectedType === 'write') {
        list = list.filter((t) => !t.read_only);
      } else if (this.selectedType === 'destructive') {
        list = list.filter((t) => t.destructive);
      }

      return list;
    },
  },

  methods: {
    setViewMode(mode) {
      this.viewMode = mode;
    },
    openSchemaModal(tool) {
      this.selectedToolForSchema = tool;
      this.showSchemaModal = true;
    },
    closeSchemaModal() {
      this.selectedToolForSchema = null;
      this.showSchemaModal = false;
    },
    copySchemaJson() {
      if (!this.selectedToolForSchema) return;
      const jsonStr = JSON.stringify(this.selectedToolForSchema.input_schema || {}, null, 2);
      navigator.clipboard.writeText(jsonStr).then(() => {
        this.$store.dispatch('showToast', {
          message: 'Schéma JSON copié dans le presse-papier !',
          type: 'success',
        });
      });
    },
    getFormattedSchema() {
      if (!this.selectedToolForSchema) return '';
      return JSON.stringify(this.selectedToolForSchema.input_schema || {}, null, 2);
    },
  },

  mounted() {
    this.$store.commit('SET_ACTIVE_TAB', 'catalog');
    this.$store.dispatch('fetchOverview');
    this.$store.dispatch('fetchTools');
  },

  template: { el: '#tpl-mcp-catalog' },
};
