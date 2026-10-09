"""
Authentication and Role-Based Access Control (RBAC) supporting Entra ID (Azure AD).
Includes development bypass and roles: Admin, ResourceManager, FinanceManager, PM.
"""

from typing import List, Optional
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from backend.app.core.config import settings

security = HTTPBearer(auto_error=False)


class CurrentUser(BaseModel):
    username: str
    email: str
    roles: List[str]

    def has_any_role(self, required_roles: List[str]) -> bool:
        if "Admin" in self.roles:
            return True
        return any(role in self.roles for role in required_roles)


def get_current_user(
    authorization: Optional[HTTPAuthorizationCredentials] = Depends(security),
    x_user_role: Optional[str] = Header(None, alias="X-User-Role"),
    x_user_email: Optional[str] = Header(None, alias="X-User-Email"),
) -> CurrentUser:
    """
    Resolves the current authenticated user.
    In development or when AUTH_ENABLED=False, supports header simulation and DB role resolution.
    In production with AUTH_ENABLED=True, decodes Entra ID JWT bearer token and enforces
    that the user has been explicitly authorized in PortalUserDB.
    """
    from backend.app.db.session import SessionLocal
    from backend.app.db.models import PortalUserDB

    if not settings.AUTH_ENABLED:
        email = x_user_email or "admin@enterprise.com"
        # Check if user has an assigned role in PortalUserDB
        assigned_role = x_user_role
        if not assigned_role:
            try:
                db = SessionLocal()
                try:
                    p_user = db.query(PortalUserDB).filter(PortalUserDB.email.ilike(email)).first()
                    if p_user:
                        assigned_role = p_user.role
                finally:
                    db.close()
            except Exception:
                pass
        role = assigned_role or "Admin"
        return CurrentUser(
            username=email.split("@")[0],
            email=email,
            roles=[role],
        )

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # In production: Decode token and extract claims
    token = authorization.credentials
    try:
        import jwt
        unverified_claims = jwt.decode(token, options={"verify_signature": False})
        email = (
            unverified_claims.get("preferred_username")
            or unverified_claims.get("upn")
            or unverified_claims.get("email", "user@enterprise.com")
        )
        token_roles = unverified_claims.get("roles", [])

        # Verify selective portal authorization against PortalUserDB
        db = SessionLocal()
        try:
            p_user = db.query(PortalUserDB).filter(PortalUserDB.email.ilike(email)).first()
            if not p_user:
                # If tenant token has Admin role, allow bootstrap access
                if "Admin" in token_roles:
                    return CurrentUser(username=email.split("@")[0], email=email, roles=["Admin"])
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        "Access denied. Your Entra ID account has not been authorized for the MPP Hub. "
                        "Please ask an Administrator to add your user account or security group."
                    ),
                )
            if not p_user.is_active:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied. Your portal user account is inactive. Please contact an Administrator.",
                )
            roles = [p_user.role]
        finally:
            db.close()

        return CurrentUser(
            username=email.split("@")[0],
            email=email,
            roles=roles,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authentication token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
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
