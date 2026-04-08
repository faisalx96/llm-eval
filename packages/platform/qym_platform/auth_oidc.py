from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from fastapi import HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from qym_platform.db.models import User, UserIdentity, UserRole
from qym_platform.settings import PlatformSettings


SESSION_USER_ID_KEY = "qym_user_id"
SESSION_PROVIDER_KEY = "qym_auth_provider"
SESSION_NEXT_KEY = "qym_auth_next"


@dataclass(frozen=True)
class ProviderIdentity:
    provider: str
    subject: str
    email: str
    email_verified: bool
    display_name: str
    raw_claims: Dict[str, Any]


def auth_mode_is_oidc(settings: PlatformSettings) -> bool:
    return str(settings.auth_mode).lower() == "oidc"


def local_auth_enabled(settings: PlatformSettings) -> bool:
    return bool(settings.auth_local_enabled) and str(settings.auth_mode).lower() != "none"


def session_auth_enabled(settings: PlatformSettings) -> bool:
    return auth_mode_is_oidc(settings) or local_auth_enabled(settings)


def enabled_provider_names(settings: PlatformSettings) -> list[str]:
    enabled: list[str] = []
    if settings.auth_google_client_id and settings.auth_google_client_secret:
        enabled.append("google")
    if settings.auth_github_client_id and settings.auth_github_client_secret:
        enabled.append("github")
    return enabled


def provider_catalog(settings: PlatformSettings) -> list[dict[str, Any]]:
    enabled = set(enabled_provider_names(settings)) if auth_mode_is_oidc(settings) else set()
    providers = [
        {
            "id": "google",
            "label": "Continue with Google",
            "enabled": "google" in enabled,
            "kind": "social",
        },
        {
            "id": "github",
            "label": "Continue with GitHub",
            "enabled": "github" in enabled,
            "kind": "social",
        },
        {
            "id": "sso",
            "label": "Continue with SSO",
            "enabled": False,
            "kind": "enterprise",
            "coming_soon": True,
        },
    ]
    return providers


def sanitize_next(next_value: Optional[str]) -> str:
    value = (next_value or "").strip()
    if not value:
        return "/"
    if not value.startswith("/"):
        return "/"
    if value.startswith("//"):
        return "/"
    return value


def _session_store(request: Request) -> dict[str, Any]:
    session = request.scope.get("session")
    if isinstance(session, dict):
        return session
    return {}


def store_login_next(request: Request, next_value: Optional[str]) -> str:
    sanitized = sanitize_next(next_value)
    request.scope.setdefault("session", {})[SESSION_NEXT_KEY] = sanitized
    return sanitized


def pop_login_next(request: Request) -> str:
    return sanitize_next(_session_store(request).pop(SESSION_NEXT_KEY, "/"))


def set_authenticated_session(request: Request, user: User, provider: str) -> None:
    session = request.scope.setdefault("session", {})
    session[SESSION_USER_ID_KEY] = str(user.id)
    session[SESSION_PROVIDER_KEY] = provider


def clear_authenticated_session(request: Request) -> None:
    _session_store(request).clear()


def get_session_user_and_provider(db: Session, request: Request) -> Optional[tuple[User, Optional[str]]]:
    session = _session_store(request)
    user_id = session.get(SESSION_USER_ID_KEY)
    if not user_id:
        return None
    user = db.query(User).filter(User.id == str(user_id)).first()
    if not user or not user.is_active:
        session.clear()
        return None
    return user, session.get(SESSION_PROVIDER_KEY)


def _default_display_name(email: str, display_name: str = "") -> str:
    display_name = (display_name or "").strip()
    if display_name:
        return display_name
    local = (email or "").split("@", 1)[0].strip()
    if not local:
        return email
    parts = [part for part in local.replace(".", " ").replace("_", " ").replace("-", " ").split() if part]
    if not parts:
        return email
    return " ".join(part.capitalize() for part in parts)


def resolve_or_provision_user(db: Session, identity: ProviderIdentity) -> User:
    if not identity.email_verified or not identity.email:
        raise HTTPException(status_code=401, detail="Provider account does not expose a verified email")

    existing_identity = (
        db.query(UserIdentity)
        .filter(UserIdentity.provider == identity.provider, UserIdentity.subject == identity.subject)
        .first()
    )
    if existing_identity:
        user = db.query(User).filter(User.id == existing_identity.user_id).first()
        if not user or not user.is_active:
            raise HTTPException(status_code=403, detail="User disabled")
        return user

    user = db.query(User).filter(User.email == identity.email).first()
    created_user = False
    if not user:
        user = User(
            email=identity.email,
            display_name=_default_display_name(identity.email, identity.display_name),
            role=UserRole.MEMBER,
            is_active=True,
        )
        db.add(user)
        db.flush()
        created_user = True
    elif not user.is_active:
        raise HTTPException(status_code=403, detail="User disabled")
    elif not user.display_name and identity.display_name:
        user.display_name = identity.display_name.strip()

    db.add(
        UserIdentity(
            user_id=user.id,
            provider=identity.provider,
            subject=identity.subject,
            email=identity.email,
            raw_claims=identity.raw_claims,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        resolved = db.query(User).filter(User.email == identity.email).first()
        if resolved and resolved.is_active:
            return resolved
        raise
    db.refresh(user)
    if created_user and not user.display_name:
        user.display_name = _default_display_name(identity.email)
        db.commit()
        db.refresh(user)
    return user


def _oauth_client(settings: PlatformSettings, provider: str):
    try:
        from authlib.integrations.starlette_client import OAuth
    except ImportError as exc:
        raise RuntimeError("Authlib is required for OIDC login. Install qym-platform with auth dependencies.") from exc

    oauth = OAuth()
    if provider == "google":
        oauth.register(
            name="google",
            client_id=settings.auth_google_client_id,
            client_secret=settings.auth_google_client_secret,
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )
    elif provider == "github":
        oauth.register(
            name="github",
            client_id=settings.auth_github_client_id,
            client_secret=settings.auth_github_client_secret,
            access_token_url="https://github.com/login/oauth/access_token",
            authorize_url="https://github.com/login/oauth/authorize",
            api_base_url="https://api.github.com/",
            client_kwargs={"scope": "read:user user:email"},
        )
    else:
        raise HTTPException(status_code=404, detail="Unknown provider")

    client = oauth.create_client(provider)
    if client is None:
        raise HTTPException(status_code=400, detail=f"{provider} login is not configured")
    return client


async def begin_provider_login(request: Request, provider: str, settings: PlatformSettings):
    if provider == "sso":
        raise HTTPException(status_code=501, detail="SSO login is not configured yet")
    client = _oauth_client(settings, provider)
    redirect_uri = f"{settings.base_url.rstrip('/')}/v1/auth/callback/{provider}"
    if provider == "google":
        return await client.authorize_redirect(request, redirect_uri, prompt="select_account")
    return await client.authorize_redirect(request, redirect_uri)


async def exchange_provider_identity(request: Request, provider: str, settings: PlatformSettings) -> ProviderIdentity:
    client = _oauth_client(settings, provider)
    token = await client.authorize_access_token(request)

    if provider == "google":
        userinfo = token.get("userinfo")
        if not userinfo:
            userinfo = await client.userinfo(token=token)
        email = str(userinfo.get("email") or "").strip().lower()
        if not email or not bool(userinfo.get("email_verified")):
            raise HTTPException(status_code=401, detail="Google account must provide a verified email")
        subject = str(userinfo.get("sub") or "").strip()
        if not subject:
            raise HTTPException(status_code=401, detail="Google identity is missing subject")
        return ProviderIdentity(
            provider="google",
            subject=subject,
            email=email,
            email_verified=True,
            display_name=str(userinfo.get("name") or userinfo.get("given_name") or "").strip(),
            raw_claims=dict(userinfo),
        )

    if provider == "github":
        profile_response = await client.get("user", token=token)
        emails_response = await client.get("user/emails", token=token)
        profile = dict(profile_response.json())
        emails = list(emails_response.json() or [])
        verified_email = None
        for item in emails:
            if item.get("verified") and item.get("primary"):
                verified_email = item.get("email")
                break
        if not verified_email:
            for item in emails:
                if item.get("verified"):
                    verified_email = item.get("email")
                    break
        email = str(verified_email or "").strip().lower()
        if not email:
            raise HTTPException(status_code=401, detail="GitHub account must provide a verified email")
        subject = str(profile.get("id") or "").strip()
        if not subject:
            raise HTTPException(status_code=401, detail="GitHub identity is missing subject")
        display_name = str(profile.get("name") or profile.get("login") or "").strip()
        raw_claims = {"profile": profile, "emails": emails}
        return ProviderIdentity(
            provider="github",
            subject=subject,
            email=email,
            email_verified=True,
            display_name=display_name,
            raw_claims=raw_claims,
        )

    raise HTTPException(status_code=404, detail="Unknown provider")


def origin_matches_base(origin: str, base_url: str) -> bool:
    try:
        o = urlparse(origin)
        b = urlparse(base_url)
    except Exception:
        return False
    return bool(o.scheme and o.netloc and b.scheme and b.netloc and o.scheme == b.scheme and o.netloc == b.netloc)
