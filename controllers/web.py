import json
from core.page_builder import Page, Component
from core.routing import Request, Response
from base.components import admin_layout
from ..services.tool_registry import ToolRegistry
from ..services.auditor import MCPAuditor
from ..services.api_key_service import MCPApiKeyService
from ..config import CONTRACT_VERSION, MCP_INTERNAL_KEY, MCP_SERVER_URL, MCP_SERVER_API_KEY


class MCPWebController:
    """Contrôleur Web d'administration pour melodi_mcp."""

    @staticmethod
    async def admin_dashboard(request: Request, response: Response):
        """Page principale d'administration : sert la coquille unique de la SPA MelodiJS."""
        content = Component(module_name="melodi_mcp", name="mcp_shell", context={
            "contract_version": CONTRACT_VERSION,
        })
        page = Page("Model Context Protocol (MCP)", admin_layout(content))
        return await response.render_page(page)

    @staticmethod
    async def admin_audit(request: Request, response: Response):
        """Page d'historique et d'audit des exécutions d'outils MCP."""
        registry = ToolRegistry.get_instance(app=request.app)
        auditor = MCPAuditor(app=request.app)

        filter_tool = request.query.get("tool")
        filter_status = request.query.get("status")

        logs = await auditor.list_recent_executions(
            tool_name=filter_tool,
            status=filter_status,
            limit=100
        )

        all_tools = registry.list_tools(enabled_only=False, check_module_active=False)
        available_tool_names = sorted([t.name for t in all_tools])

        content = Component(module_name="melodi_mcp", name="mcp_shell", context={
            "logs": logs,
            "available_tools": available_tool_names,
            "filter_tool": filter_tool or "",
            "filter_status": filter_status or "",
        })

        page = Page("Journal d'Audit MCP", admin_layout(content))
        return await response.render_page(page)

    @staticmethod
    async def admin_manifest(request: Request, response: Response):
        """Page d'état, manifeste et paramètres de connexion pour melodi_mcp_server."""
        app = getattr(request, "app", None) or (getattr(request.module, "app", None) if hasattr(request, "module") else None)
        registry = ToolRegistry.get_instance(app=app)
        api_key_service = MCPApiKeyService(app=app)
        current_rev = registry.get_revision()

        message = None
        message_type = None
        action = None

        if request.method == "POST":
            form = request.form or {}
            action = form.get("action")
            if action in ("update_key", "update", None):
                new_key = (form.get("internal_key") or "").strip()
                if not new_key and form.get("generate") == "1":
                    new_key = api_key_service.generate_secret_token(prefix="mcp_internal_")
                if new_key:
                    await api_key_service.update_internal_key(new_key)
                    message = "Clé d'authentification interne mise à jour avec succès."
                    message_type = "success"
                else:
                    message = "Veuillez fournir une clé d'authentification valide ou générer une nouvelle valeur."
                    message_type = "danger"
            elif action == "update_jwt_secret":
                new_secret = (form.get("jwt_secret") or "").strip()
                if not new_secret and form.get("generate") == "1":
                    import secrets
                    new_secret = secrets.token_urlsafe(32)
                if new_secret:
                    await api_key_service.update_jwt_secret(new_secret)
                    message = "Clé secrète de chiffrement JWT mise à jour avec succès."
                    message_type = "success"
                else:
                    message = "Veuillez fournir une clé secrète JWT valide."
                    message_type = "danger"
            elif action == "update_server":
                new_url = (form.get("mcp_server_url") or "").strip()
                new_mcp_api_key = (form.get("mcp_server_api_key") or "").strip()
                if new_url:
                    await api_key_service.update_server_url(new_url)
                if new_mcp_api_key:
                    await api_key_service.update_server_api_key(new_mcp_api_key)
                message = "Paramètres de connexion au serveur MCP mis à jour avec succès."
                message_type = "success"

        internal_key = api_key_service.get_internal_key()
        jwt_secret = api_key_service.get_jwt_secret()
        mcp_server_url = api_key_service.get_server_url()
        mcp_server_api_key = api_key_service.get_server_api_key()

        # Construction dynamique de l'URL d'API interne sans suffixe /internal
        host = getattr(request, "host", "") or "localhost:5000"
        scheme = getattr(request, "scheme", "http") or "http"
        internal_api_url = f"{scheme}://{host}/api/melodi_mcp"

        manifest_data = {
            "contract_version": CONTRACT_VERSION,
            "melodi_version": getattr(getattr(app, "config", None), "VERSION", "1.0.0"),
            "catalog_revision": current_rev,
            "tools_count": registry.count(enabled_only=True),
            "capabilities": {
                "tools_discovery": True,
                "tool_execution": True,
                "etag_support": True,
                "dynamic_reload": True,
            },
            "server_info": {
                "provider": "MELODI ERP melodi_mcp",
                "auth_modes": ["bearer_jwt", "service_key"],
                "internal_endpoint": "/api/melodi_mcp",
                "api_url": internal_api_url,
            }
        }

        content = Component(module_name="melodi_mcp", name="mcp_shell", context={
            "contract_version": CONTRACT_VERSION,
            "catalog_revision": current_rev,
            "internal_key": internal_key,
            "internal_api_url": internal_api_url,
            "internal_endpoint": "/api/melodi_mcp",
            "jwt_secret": jwt_secret,
            "mcp_server_url": mcp_server_url,
            "mcp_server_api_key": mcp_server_api_key,
            "manifest_json": json.dumps(manifest_data, indent=2, ensure_ascii=False),
            "message": message,
            "message_type": message_type,
        })

        page = Page("Serveur MCP & Manifeste", admin_layout(content))
        return await response.render_page(page)

    @staticmethod
    async def admin_api_keys(request: Request, response: Response):
        """Page de génération et de gestion des tokens MCP de l'utilisateur en cours (validité 7 jours par défaut)."""
        app = getattr(request, "app", None) or (getattr(request.module, "app", None) if hasattr(request, "module") else None)
        api_key_service = MCPApiKeyService(app=app)

        # Récupération de l'utilisateur actuellement connecté (data_context, request.get_session ou quart.session)
        user_payload = None
        if hasattr(request, "data_context") and isinstance(request.data_context, dict):
            user_payload = request.data_context.get("user_payload")

        if not user_payload and hasattr(request, "get_session") and callable(request.get_session):
            raw_session = request.get_session("user_payload")
            if isinstance(raw_session, (str, dict)):
                try:
                    user_payload = json.loads(raw_session) if isinstance(raw_session, str) else raw_session
                except Exception:
                    user_payload = None

        if not user_payload:
            try:
                from quart import session as quart_session
                raw_q = quart_session.get("user_payload")
                if isinstance(raw_q, (str, dict)):
                    user_payload = json.loads(raw_q) if isinstance(raw_q, str) else raw_q
            except Exception:
                user_payload = None

        user_id = "system"
        username = "Utilisateur"
        is_sudo = False
        user_permissions = []

        if isinstance(user_payload, dict) and user_payload.get("user_id"):
            user_id = str(user_payload["user_id"])
            username = str(user_payload.get("username") or user_payload.get("email") or user_id)
            is_sudo = bool(user_payload.get("is_sudo", False))
            if app and hasattr(app, "cache") and app.cache:
                perms_map = app.cache.get("user_permissions") or {}
                user_permissions = list(perms_map.get(user_id, []))
            elif isinstance(user_payload.get("permissions"), list):
                user_permissions = list(user_payload["permissions"])

        newly_created_key = None
        message = None
        message_type = None
        action = None

        if request.method == "POST":
            form = request.form or {}
            action = form.get("action")

            if action == "create":
                name = (form.get("name") or "").strip() or f"Token MCP - {username}"
                raw_hours = form.get("expires_in_hours")
                raw_days = form.get("expires_in_days")
                try:
                    if raw_hours not in (None, ""):
                        expires_in_hours = int(raw_hours)
                    elif raw_days not in (None, ""):
                        expires_in_hours = int(raw_days) * 24
                    else:
                        expires_in_hours = 24
                except (ValueError, TypeError):
                    expires_in_hours = 24

                expires_in_hours = max(1, min(72, expires_in_hours))

                key_obj, raw_key = await api_key_service.create_key(
                    name=name,
                    role="user",
                    permissions="*",
                    created_by=user_id,
                    expires_in_hours=expires_in_hours,
                )
                if key_obj:
                    newly_created_key = raw_key
                    message = f"Token personnel '{name}' généré pour {username} (valable {expires_in_hours}h)."
                    message_type = "success"
                else:
                    message = "Erreur lors de la génération du token utilisateur."
                    message_type = "danger"

            elif action == "toggle":
                try:
                    key_id = int(form.get("key_id", 0))
                    res = await api_key_service.toggle_status(key_id)
                    if res:
                        state_str = "activé" if res["is_active"] else "révoqué"
                        message = f"Token {state_str} avec succès."
                        message_type = "info"
                except Exception as e:
                    message = f"Erreur de modification du statut: {e}"
                    message_type = "danger"

            elif action == "delete":
                try:
                    key_id = int(form.get("key_id", 0))
                    deleted = await api_key_service.delete_key(key_id)
                    if deleted:
                        message = "Token supprimé avec succès."
                        message_type = "warning"
                except Exception as e:
                    message = f"Erreur lors de la suppression: {e}"
                    message_type = "danger"

        # Liste uniquement les tokens de l'utilisateur en cours (ou tous si test unitaire sans session user)
        filter_user_id = user_id if user_id != "system" else None
        keys = await api_key_service.list_keys(user_id=filter_user_id)

        content = Component(module_name="melodi_mcp", name="mcp_shell", context={
            "keys": keys,
            "current_user_id": user_id,
            "current_username": username,
            "current_user_is_sudo": is_sudo,
            "current_user_permissions": user_permissions,
            "contract_version": CONTRACT_VERSION,
            "mcp_server_url": api_key_service.get_server_url(),
            "mcp_api_key": api_key_service.get_server_api_key(),
            "newly_created_key": newly_created_key,
            "message": message,
            "message_type": message_type,
        })

        page = Page("Mes Tokens MCP (Agent IA)", admin_layout(content))
        return await response.render_page(page)

    @staticmethod
    async def admin_oauth_authorize(request: Request, response: Response):
        """Page d'autorisation et consentement OAuth 2.0 pour assistants IA."""
        app = getattr(request, "app", None) or (getattr(request.module, "app", None) if hasattr(request, "module") else None)
        from ..services.oauth_service import MCPOAuthService
        oauth_service = MCPOAuthService.get_instance(app=app)

        query = getattr(request, "query", {}) or {}
        form = getattr(request, "form", {}) or {}
        params = {**query, **form}

        client_id = (params.get("client_id") or "ai_client").strip()
        redirect_uri = (params.get("redirect_uri") or "").strip()
        state = params.get("state")
        code_challenge = params.get("code_challenge")
        code_challenge_method = params.get("code_challenge_method")

        # Identification de l'utilisateur connecté
        user_payload = None
        if hasattr(request, "data_context") and isinstance(request.data_context, dict):
            user_payload = request.data_context.get("user_payload")

        if not user_payload and hasattr(request, "get_session") and callable(request.get_session):
            raw_session = request.get_session("user_payload")
            if isinstance(raw_session, (str, dict)):
                try:
                    user_payload = json.loads(raw_session) if isinstance(raw_session, str) else raw_session
                except Exception:
                    user_payload = None

        if not user_payload:
            try:
                from quart import session as quart_session
                raw_q = quart_session.get("user_payload")
                if isinstance(raw_q, (str, dict)):
                    user_payload = json.loads(raw_q) if isinstance(raw_q, str) else raw_q
            except Exception:
                user_payload = None

        if not user_payload or not user_payload.get("user_id"):
            import urllib.parse
            full_path = request.path
            if getattr(request, "query_string", None):
                full_path += f"?{request.query_string}"
            return response.redirect(f"/auth/login?redirect={urllib.parse.quote(full_path)}")

        user_id = str(user_payload["user_id"])
        username = str(user_payload.get("username") or user_payload.get("email") or user_id)

        # Traitement POST : approbation ou refus
        if request.method == "POST":
            action = form.get("action")
            if action == "deny":
                sep = "&" if "?" in redirect_uri else "?"
                target = f"{redirect_uri}{sep}error=access_denied&error_description=Consentement+refuse"
                if state:
                    target += f"&state={state}"
                return response.redirect(target)

            if not redirect_uri:
                content = Component(module_name="melodi_mcp", name="oauth_authorize", context={
                    "client_id": client_id,
                    "username": username,
                    "user_id": user_id,
                    "redirect_uri": redirect_uri,
                    "state": state,
                    "code_challenge": code_challenge,
                    "code_challenge_method": code_challenge_method,
                    "error_message": "Paramètre obligatoire 'redirect_uri' manquant.",
                })
                page = Page("Autorisation Assistant IA", admin_layout(content))
                return await response.render_page(page)

            code = oauth_service.create_authorization_code(
                client_id=client_id,
                redirect_uri=redirect_uri,
                user_id=user_id,
                code_challenge=code_challenge,
                code_challenge_method=code_challenge_method,
                ttl_seconds=300,
            )

            sep = "&" if "?" in redirect_uri else "?"
            target = f"{redirect_uri}{sep}code={code}"
            if state:
                target += f"&state={state}"
            return response.redirect(target)

        # Affichage GET : formulaire de consentement
        content = Component(module_name="melodi_mcp", name="oauth_authorize", context={
            "client_id": client_id,
            "username": username,
            "user_id": user_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "error_message": None,
        })
        page = Page("Autorisation Assistant IA", admin_layout(content))
        return await response.render_page(page)

    @staticmethod
    async def admin_server_dashboard(request: Request, response: Response):
        """Page d'administration et supervision en direct du serveur MCP (melodi_mcp_server)."""
        import time
        import httpx
        app = getattr(request, "app", None) or (getattr(request.module, "app", None) if hasattr(request, "module") else None)
        registry = ToolRegistry.get_instance(app=app)
        api_key_service = MCPApiKeyService(app=app)

        mcp_server_url = api_key_service.get_server_url() or "http://localhost:8765/mcp"
        clean_url = mcp_server_url.rstrip("/")
        for suffix in ("/mcp", "/sse"):
            if clean_url.endswith(suffix):
                clean_url = clean_url[:-len(suffix)].rstrip("/")
                break
        server_base_url = clean_url or "http://localhost:8765"

        message = None
        message_type = None
        action = None

        if request.method == "POST":
            form = request.form or {}
            action = form.get("action")
            if action == "force_sync":
                try:
                    async with httpx.AsyncClient(timeout=4.0) as client:
                        internal_key = api_key_service.get_internal_key()
                        headers = {
                            "Authorization": f"Bearer {internal_key}",
                            "X-Internal-MCP-Key": internal_key,
                        }
                        # Appel de l'endpoint dédié de synchronisation
                        sync_resp = await client.post(f"{server_base_url}/api/mcp/sync", headers=headers)
                        if sync_resp.status_code == 404:
                            sync_resp = await client.post(f"{server_base_url}/admin/api/sync", headers=headers)
                        if sync_resp.status_code == 200:
                            sdata = sync_resp.json() if hasattr(sync_resp, "json") else {}
                            cnt = sdata.get("tools_count", "N/A")
                            message = f"Synchronisation réussie ! {cnt} outils synchronisés sur le serveur MCP."
                            message_type = "success"
                        else:
                            message = f"Le serveur MCP a répondu avec le statut {sync_resp.status_code} lors de la synchronisation."
                            message_type = "warning"
                except Exception as e:
                    message = f"Impossible de joindre le serveur MCP pour forcer la synchronisation : {e}"
                    message_type = "danger"
            elif action == "ping":
                # Le test est automatiquement réexécuté ci-dessous
                pass

        # Test de santé et métriques en direct
        is_online = False
        latency_ms = None
        server_status = "UNHEALTHY"
        server_tools_count = 0
        server_revision = None
        server_uptime = None
        server_version = "0.1.0"
        error_detail = None

        start_time = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                health_resp = await client.get(f"{server_base_url}/health")
                elapsed = time.monotonic() - start_time
                latency_ms = round(elapsed * 1000, 1)

                if health_resp.status_code == 200:
                    is_online = True
                    hdata = health_resp.json()
                    server_status = hdata.get("status", "HEALTHY")
                    server_tools_count = hdata.get("tools_count", 0)
                    server_revision = hdata.get("catalog_revision") or hdata.get("revision")
                    server_uptime = hdata.get("uptime") or "En ligne"
                    server_version = hdata.get("version", "0.1.0")
                    if action == "ping":
                        message = f"Connexion réussie au serveur MCP ! Latence mesurée : {latency_ms} ms."
                        message_type = "success"
                else:
                    server_status = "DEGRADED"
                    error_detail = f"Code HTTP {health_resp.status_code}"
                    if action == "ping":
                        message = f"Le serveur MCP a répondu avec une anomalie : {health_resp.status_code}."
                        message_type = "warning"
        except Exception as e:
            is_online = False
            server_status = "UNHEALTHY"
            error_detail = "Impossible de se connecter à " + server_base_url
            if action == "ping":
                message = f"Échec de la connexion au serveur MCP ({server_base_url}) : {e}"
                message_type = "danger"

        content = Component(module_name="melodi_mcp", name="mcp_shell", context={
            "mcp_server_url": mcp_server_url,
            "server_base_url": server_base_url,
            "is_online": is_online,
            "latency_ms": latency_ms or 0,
            "server_status": server_status,
            "server_tools_count": server_tools_count,
            "total_erp_tools": registry.count(enabled_only=True),
            "catalog_revision": registry.get_revision(),
            "server_revision": server_revision,
            "server_uptime": server_uptime or "-",
            "server_version": server_version,
            "error_detail": error_detail,
            "jwt_secret_set": bool(api_key_service.get_jwt_secret()),
            "mcp_api_key_set": bool(api_key_service.get_server_api_key()),
            "message": message,
            "message_type": message_type,
        })
        page = Page("Administration Serveur MCP", admin_layout(content))
        return await response.render_page(page)
