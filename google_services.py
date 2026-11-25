"""Camada de autenticação Google OAuth 2.0 e clientes da API Google (Agenda, Gmail, Drive e Tarefas)."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import database

logger = logging.getLogger("jarvis.google")

GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"

GOOGLE_SCOPES: list[str] = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/tasks",
]

# Estados OAuth pendentes (TTL de 15 minutos) para validação de state e PKCE code_verifier
_OAUTH_STATE_TTL_SECONDS = 900
_PENDING_OAUTH_STATES: dict[str, dict[str, Any]] = {}


class GoogleOAuthConfigError(RuntimeError):
    """Credenciais OAuth do Google ausentes no ambiente."""


class GoogleAuthRequiredError(RuntimeError):
    """Conta Google ainda não conectada ou credenciais expiradas sem refresh_token."""


def get_google_oauth_config(fallback_redirect_uri: str | None = None) -> dict[str, Any]:
    """Lê GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET e GOOGLE_REDIRECT_URI do ambiente."""
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI", "").strip() or (fallback_redirect_uri or "").strip()
    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "configured": bool(client_id and client_secret and redirect_uri),
    }


def _prune_expired_states() -> None:
    cutoff = time.time() - _OAUTH_STATE_TTL_SECONDS
    expired = [k for k, v in _PENDING_OAUTH_STATES.items() if v.get("created_at", 0) < cutoff]
    for k in expired:
        _PENDING_OAUTH_STATES.pop(k, None)


def _client_config_dict(client_id: str, client_secret: str, redirect_uri: str) -> dict[str, Any]:
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": GOOGLE_AUTH_URI,
            "token_uri": GOOGLE_TOKEN_URI,
            "redirect_uris": [redirect_uri],
        }
    }


def _parse_utc_naive_expiry(expiry_str: str | None) -> datetime | None:
    """Converte string ISO em datetime UTC naive (formato esperado por google.oauth2.credentials.Credentials)."""
    if not expiry_str:
        return None
    try:
        dt = datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except ValueError:
        return None


def _format_expiry(expiry_dt: datetime | None) -> str | None:
    if expiry_dt is None:
        return None
    if expiry_dt.tzinfo is not None:
        expiry_dt = expiry_dt.astimezone(timezone.utc).replace(tzinfo=None)
    return expiry_dt.isoformat(timespec="seconds") + "Z"


def start_oauth_flow(fallback_redirect_uri: str | None = None) -> tuple[str, str]:
    """Cria a URL de autorização OAuth 2.0 com access_type='offline' e prompt='consent'."""
    from google_auth_oauthlib.flow import Flow

    cfg = get_google_oauth_config(fallback_redirect_uri=fallback_redirect_uri)
    if not cfg["configured"]:
        raise GoogleOAuthConfigError(
            "Credenciais Google OAuth não configuradas. Defina GOOGLE_CLIENT_ID, "
            "GOOGLE_CLIENT_SECRET e GOOGLE_REDIRECT_URI nas variáveis de ambiente."
        )

    _prune_expired_states()

    flow = Flow.from_client_config(
        _client_config_dict(cfg["client_id"], cfg["client_secret"], cfg["redirect_uri"]),
        scopes=GOOGLE_SCOPES,
    )
    flow.redirect_uri = cfg["redirect_uri"]

    authorization_url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )

    _PENDING_OAUTH_STATES[state] = {
        "created_at": time.time(),
        "redirect_uri": cfg["redirect_uri"],
        "code_verifier": getattr(flow, "code_verifier", None),
    }

    return authorization_url, state


def exchange_code_for_tokens(
    code: str,
    state: str | None = None,
    fallback_redirect_uri: str | None = None,
) -> dict[str, Any]:
    """Troca o authorization code por tokens OAuth 2.0 e grava na tabela google_tokens do SQLite."""
    from google_auth_oauthlib.flow import Flow

    _prune_expired_states()
    pending = _PENDING_OAUTH_STATES.pop(state, None) if state else None
    effective_redirect = (pending or {}).get("redirect_uri") or fallback_redirect_uri

    cfg = get_google_oauth_config(fallback_redirect_uri=effective_redirect)
    if not cfg["configured"]:
        raise GoogleOAuthConfigError(
            "Credenciais Google OAuth não configuradas no servidor."
        )

    # Evita erro quando o Google retorna escopos reordenados ou expandidos
    os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

    flow = Flow.from_client_config(
        _client_config_dict(cfg["client_id"], cfg["client_secret"], cfg["redirect_uri"]),
        scopes=GOOGLE_SCOPES,
        state=state,
    )
    flow.redirect_uri = cfg["redirect_uri"]
    if pending and pending.get("code_verifier"):
        flow.code_verifier = pending["code_verifier"]

    flow.fetch_token(code=code)
    creds = flow.credentials

    account_email = _fetch_account_email(creds)
    saved = database.save_google_tokens(
        token=creds.token,
        refresh_token=creds.refresh_token,
        token_uri=creds.token_uri or GOOGLE_TOKEN_URI,
        client_id=creds.client_id or cfg["client_id"],
        client_secret=creds.client_secret or cfg["client_secret"],
        scopes=list(creds.scopes or GOOGLE_SCOPES),
        expiry=_format_expiry(creds.expiry),
        email=account_email,
    )
    logger.info("Conta Google conectada com sucesso | email=%s | refresh_token=%s", account_email, bool(saved.get("refresh_token")))
    return saved


def _fetch_account_email(creds: Any) -> str | None:
    """Tenta descobrir o e-mail da conta Google conectada via perfil do Gmail (sem escopo extra)."""
    try:
        from googleapiclient.discovery import build

        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        profile = service.users().getProfile(userId="me").execute()
        return profile.get("emailAddress")
    except Exception as exc:
        logger.debug("Não foi possível obter e-mail do perfil Gmail: %s", exc)
        return None


def get_valid_credentials(
    auto_refresh: bool = True,
    fallback_redirect_uri: str | None = None,
) -> tuple[Any | None, dict[str, Any]]:
    """Carrega credenciais do SQLite, renova automaticamente via refresh_token se expiradas e retorna (creds, status)."""
    cfg = get_google_oauth_config(fallback_redirect_uri=fallback_redirect_uri)
    stored = database.get_google_tokens()

    if not stored or not stored.get("token"):
        return None, {
            "connected": False,
            "configured": cfg["configured"],
            "email": None,
            "scopes": [],
            "expiry": None,
            "has_refresh_token": False,
            "refreshed": False,
        }

    from google.auth.transport.requests import Request as GoogleAuthRequest
    from google.oauth2.credentials import Credentials

    creds = Credentials(
        token=stored["token"],
        refresh_token=stored.get("refresh_token"),
        token_uri=stored.get("token_uri") or GOOGLE_TOKEN_URI,
        client_id=stored.get("client_id") or cfg["client_id"] or None,
        client_secret=stored.get("client_secret") or cfg["client_secret"] or None,
        scopes=stored.get("scopes") or GOOGLE_SCOPES,
        expiry=_parse_utc_naive_expiry(stored.get("expiry")),
    )

    refreshed = False
    refresh_error: str | None = None

    if auto_refresh and (creds.expired or not creds.valid) and creds.refresh_token:
        try:
            creds.refresh(GoogleAuthRequest())
            refreshed = True
            stored = database.save_google_tokens(
                token=creds.token,
                refresh_token=creds.refresh_token,
                token_uri=creds.token_uri or GOOGLE_TOKEN_URI,
                client_id=creds.client_id or cfg["client_id"],
                client_secret=creds.client_secret or cfg["client_secret"],
                scopes=list(creds.scopes or stored.get("scopes") or GOOGLE_SCOPES),
                expiry=_format_expiry(creds.expiry),
                email=stored.get("email"),
            )
            logger.info("Token Google renovado automaticamente via refresh_token.")
        except Exception as exc:
            refresh_error = str(exc)
            logger.warning("Falha ao renovar token Google via refresh_token: %s", exc)

    connected = bool(creds.valid)
    status_info: dict[str, Any] = {
        "connected": connected,
        "configured": cfg["configured"],
        "email": stored.get("email"),
        "scopes": stored.get("scopes") or [],
        "expiry": stored.get("expiry"),
        "has_refresh_token": bool(creds.refresh_token),
        "refreshed": refreshed,
    }
    if refresh_error:
        status_info["error"] = refresh_error

    return (creds if connected else None), status_info


def build_google_service(api_name: str, api_version: str) -> Any:
    """Retorna um cliente autenticado da Google API (calendar, gmail, drive ou tasks)."""
    creds, info = get_valid_credentials(auto_refresh=True)
    if creds is None:
        if info.get("error"):
            raise GoogleAuthRequiredError(
                "A sessão Google expirou e não pôde ser renovada automaticamente. "
                "Clique em 'Conectar Google' no topo do HUD para reconectar."
            )
        raise GoogleAuthRequiredError(
            "A conta Google ainda não está conectada. "
            "Clique no botão 'Conectar Google' no topo do HUD para autorizar o acesso."
        )

    from googleapiclient.discovery import build

    return build(api_name, api_version, credentials=creds, cache_discovery=False)
