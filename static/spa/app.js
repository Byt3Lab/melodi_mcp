import{createApp as i}from"/static/base/melodiJS/index.js";import{router as n}from"./router.js";import{store as o}from"./store.js";function s(){const a=document.getElementById("mcp-app");if(!a)return;const t=i({delimiters:["[[","]]"],computed:{activeTab(){return this.$store.state.activeTab||"catalog"},toast(){return this.$store.state.toast},isOnline(){return!!this.$store.state.serverStatus.is_online}},methods:{navigateTo(e){this.$router.push(e)}},template:`
      <div class="mcp-spa-root">
        <!-- Navigation par onglets SPA -->
        <nav class="mcp-nav-tabs">
          <button type="button" class="mcp-nav-tab" :class="{ active: activeTab === 'catalog' }" @click="navigateTo('/')">
            <img src="/static_base_icons?name=extension&fill=currentColor" style="width: 16px; height: 16px;" alt="">
            <span>Catalogue Outils</span>
          </button>
          <button type="button" class="mcp-nav-tab" :class="{ active: activeTab === 'server' }" @click="navigateTo('/server')">
            <img src="/static_base_icons?name=dns&fill=currentColor" style="width: 16px; height: 16px;" alt="">
            <span>Supervision Serveur</span>
            <span class="mcp-pulse-dot" :class="isOnline ? 'healthy' : 'unhealthy'"></span>
          </button>
          <button type="button" class="mcp-nav-tab" :class="{ active: activeTab === 'tokens' }" @click="navigateTo('/tokens')">
            <img src="/static_base_icons?name=key&fill=currentColor" style="width: 16px; height: 16px;" alt="">
            <span>Mes Tokens IA</span>
          </button>
          <button type="button" class="mcp-nav-tab" :class="{ active: activeTab === 'audit' }" @click="navigateTo('/audit')">
            <img src="/static_base_icons?name=history&fill=currentColor" style="width: 16px; height: 16px;" alt="">
            <span>Journal d'Audit</span>
          </button>
          <button type="button" class="mcp-nav-tab" :class="{ active: activeTab === 'manifest' }" @click="navigateTo('/manifest')">
            <img src="/static_base_icons?name=settings&fill=currentColor" style="width: 16px; height: 16px;" alt="">
            <span>Configuration & Cl\xE9s</span>
          </button>
        </nav>

        <!-- Vue active pilot\xE9e par MelodiRouter -->
        <router-view></router-view>

        <!-- Toasts de notification globaux -->
        <div v-if="toast" class="mcp-toast-container">
          <div class="ds-card p-3 shadow border" :class="'border-' + toast.type" style="min-width: 280px; max-width: 420px; background: var(--ds-surface, #ffffff);">
            <div class="d-flex align-items-center justify-content-between gap-2">
              <span class="ds-text-sm fw-semibold" :class="'text-' + toast.type">[[ toast.message ]]</span>
            </div>
          </div>
        </div>
      </div>
    `});t.use(n),t.use(o),t.mount(a)}document.readyState==="loading"?document.addEventListener("DOMContentLoaded",s):setTimeout(s,0);
//# sourceMappingURL=app.js.map
