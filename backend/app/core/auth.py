"""
Authentication and Role-Based Access Control (RBAC) supporting Entra ID (Azure AD).
Includes development bypass and roles: Admin, ResourceManager, FinanceManager, PM.
"""

from typing import List, Optional
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.db.session import get_db

security = HTTPBearer(auto_error=False)


class CurrentUser(BaseModel):
    username: str
    email: str
    display_name: Optional[str] = None
    roles: List[str]

    def has_any_role(self, required_roles: List[str]) -> bool:
        if "Admin" in self.roles:
            return True
        return any(role in self.roles for role in required_roles)


def create_emergency_token(username: str) -> str:
    """Creates a signed JWT token for the Emergency / Onboarding Admin user."""
    import jwt
    from datetime import datetime, timedelta, timezone

    payload = {
        "sub": username,
        "email": username,
        "name": "Emergency Onboarding Admin",
        "roles": ["Admin"],
        "auth_type": "EMERGENCY",
        "exp": datetime.now(timezone.utc) + timedelta(hours=12),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def create_sso_session_token(email: str, display_name: str, roles: Optional[List[str]] = None) -> str:
    """
    Creates a cryptographically signed HS256 session JWT after the server-side
    Entra ID OAuth2 code exchange succeeds.
    """
    import jwt
    from datetime import datetime, timedelta, timezone

    payload = {
        "sub": email.strip().lower(),
        "email": email.strip().lower(),
        "preferred_username": email.strip().lower(),
        "name": display_name,
        "roles": roles or [],
        "auth_type": "SSO_SESSION",
        "exp": datetime.now(timezone.utc) + timedelta(hours=12),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def _verify_jwt_claims(token: str) -> dict:
    """
    Cryptographically verifies a Bearer JWT token:
    1. Verifies locally-signed HS256 tokens (Emergency Admin & Server-Exchanged Entra SSO Session tokens)
       using settings.SECRET_KEY.
    2. Otherwise, verifies RS256 tokens against Microsoft Entra ID JWKS public keys.
    Unsigned or forged tokens are strictly rejected.
    """
    import jwt

    # 1. Try locally-signed HS256 token (Emergency Admin, Server-Exchanged SSO Session, or test tokens signed with SECRET_KEY)
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token has expired. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        pass

    # 2. Try Microsoft Entra ID RS256 verification via JWKS if tenant is configured
    if settings.AZURE_AD_TENANT_ID:
        tenant_id = settings.AZURE_AD_TENANT_ID.strip()
        jwks_url = f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
        try:
            jwks_client = jwt.PyJWKClient(jwks_url)
            signing_key = jwks_client.get_signing_key_from_jwt(token)
            decode_opts = {"verify_aud": bool(settings.AZURE_AD_CLIENT_ID)}
            audience = settings.AZURE_AD_CLIENT_ID.strip() if settings.AZURE_AD_CLIENT_ID else None
            return jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=audience,
                options=decode_opts,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Entra ID JWT signature verification failed: {str(exc)}",
                headers={"WWW-Authenticate": "Bearer"},
            )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or unverified authentication token signature.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    authorization: Optional[HTTPAuthorizationCredentials] = Depends(security),
    x_user_role: Optional[str] = Header(None, alias="X-User-Role"),
    x_user_email: Optional[str] = Header(None, alias="X-User-Email"),
    db: Session = Depends(get_db),
) -> CurrentUser:
    """
    Resolves the current authenticated user.
    Supports:
    1. Emergency / Onboarding Admin JWT token (credentials stored in .env)
    2. Verified Entra ID SSO Session JWT Bearer token
    3. Least-privilege check: minimum role required to log in is PM
    4. Strict 401 rejection when AUTH_ENABLED=True and no valid Bearer token is provided
    """
    from backend.app.db.models import PortalUserDB

    # 1. Bearer Token Flow (Emergency Admin JWT or Verified Entra ID SSO JWT)
    if authorization and authorization.credentials:
        token = authorization.credentials
        try:
            verified_claims = _verify_jwt_claims(token)

            # 1a. Check if token is a locally-signed Emergency Admin token
            if verified_claims.get("auth_type") == "EMERGENCY":
                uname = verified_claims.get("sub") or settings.EMERGENCY_ADMIN_USERNAME
                return CurrentUser(
                    username=uname,
                    email=uname,
                    display_name=verified_claims.get("name", "Emergency Onboarding Admin"),
                    roles=["Admin"],
                )

            # 1b. Verified Entra ID SSO claims
            email = (
                verified_claims.get("preferred_username")
                or verified_claims.get("upn")
                or verified_claims.get("email")
                or ""
            ).strip().lower()
            if not email:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token does not contain a valid user email or UPN claim.",
                )

            name_claim = verified_claims.get("name") or email.split("@")[0].replace(".", " ").title()
            token_roles = verified_claims.get("roles", [])

            p_user = db.query(PortalUserDB).filter(PortalUserDB.email.ilike(email)).first()

            # Optional INITIAL_ADMIN_EMAIL match if configured in .env
            if not p_user and settings.INITIAL_ADMIN_EMAIL and settings.INITIAL_ADMIN_EMAIL.strip().lower() == email:
                p_user = PortalUserDB(
                    email=email,
                    display_name=name_claim,
                    role="Admin",
                    is_active=True,
                    source="INITIAL_SETUP",
                )
                db.add(p_user)
                db.commit()
                db.refresh(p_user)

            if not p_user:
                if "Admin" in token_roles:
                    return CurrentUser(username=email.split("@")[0], email=email, display_name=name_claim, roles=["Admin"])
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        f"Access denied for '{email}'. Your Microsoft Entra ID account has not been onboarded to this portal. "
                        f"Please sign in with the Emergency Onboarding Admin account or contact an Administrator to grant you PM or Admin access."
                    ),
                )

            if not p_user.is_active:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied. Your portal user account is inactive. Please contact an Administrator.",
                )

            # Least privilege requirement: minimum role is PM
            if p_user.role not in ["Admin", "FinanceManager", "ResourceManager", "PM"]:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied. The minimum privilege required to access this portal is Project Manager (PM).",
                )

            return CurrentUser(
                username=email.split("@")[0],
                email=p_user.email,
                display_name=p_user.display_name or name_claim,
                roles=[p_user.role],
            )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid authentication token: {str(e)}",
                headers={"WWW-Authenticate": "Bearer"},
            )

    # 2. Enforce mandatory login when AUTH_ENABLED is True
    if settings.AUTH_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please sign in to access application data.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 3. Test / Development Bypass (only when AUTH_ENABLED=False)
    email = (x_user_email or "admin@enterprise.com").lower()
    p_user = db.query(PortalUserDB).filter(PortalUserDB.email.ilike(email)).first()
    if p_user:
        role = p_user.role
        dname = p_user.display_name
    else:
        role = x_user_role or "Admin"
        dname = email.split("@")[0].replace(".", " ").title()

    return CurrentUser(
        username=email.split("@")[0],
        email=email,
        display_name=dname,
        roles=[role],
    )



def require_roles(allowed_roles: List[str]):
    """
    FastAPI dependency factory enforcing role permissions.
    """
    def role_checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not user.has_any_role(allowed_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Requires one of roles: {', '.join(allowed_roles)}",
            )
        return user
    return role_checker
