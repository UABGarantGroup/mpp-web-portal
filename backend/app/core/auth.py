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
    2. Entra ID JWT Bearer token (SSO login with MSAL.js)
    3. Least-privilege check: minimum role required to log in is PM
    4. Strict 401 rejection when AUTH_ENABLED=True and no valid Bearer token is provided
    """
    from backend.app.db.models import PortalUserDB

    # 1. Bearer Token Flow (Emergency Admin JWT or Entra ID SSO JWT)
    if authorization and authorization.credentials:
        token = authorization.credentials
        try:
            import jwt

            # 1a. Check if token is a locally-signed Emergency Admin token
            try:
                verified_local = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
                if verified_local.get("auth_type") == "EMERGENCY":
                    uname = verified_local.get("sub") or settings.EMERGENCY_ADMIN_USERNAME
                    return CurrentUser(
                        username=uname,
                        email=uname,
                        display_name=verified_local.get("name", "Emergency Onboarding Admin"),
                        roles=["Admin"],
                    )
            except Exception:
                pass

            # 1b. Decode Entra ID SSO JWT claims
            unverified_claims = jwt.decode(token, options={"verify_signature": False})
            email = (
                unverified_claims.get("preferred_username")
                or unverified_claims.get("upn")
                or unverified_claims.get("email")
                or ""
            ).strip().lower()
            if not email:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token does not contain a valid user email or UPN claim.",
                )

            name_claim = unverified_claims.get("name") or email.split("@")[0].replace(".", " ").title()
            token_roles = unverified_claims.get("roles", [])

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
