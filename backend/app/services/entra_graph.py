"""
Microsoft Entra ID (Azure AD) and Microsoft Graph Service.
Provides selective lookup and synchronization of users and security groups.
Supports live Microsoft Graph API calls when credentials are configured,
with a mock organizational directory fallback for development and testing.
"""

import logging
from typing import Any, Dict, List, Optional
import httpx

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

# Realistic fallback directory for development, demo, and offline testing
MOCK_SECURITY_GROUPS = [
    {
        "id": "sg-pm-001",
        "display_name": "Project Managers (Garant Group)",
        "mail": "pm-group@garantgroup.eu",
        "description": "Certified Project Managers managing shipyard and engineering contracts",
        "security_enabled": True,
        "members": [
            {
                "id": "oid-user-001",
                "display_name": "Tomas Jonaitis",
                "email": "tomas.jonaitis@garantgroup.eu",
                "upn": "tomas.jonaitis@garantgroup.eu",
                "job_title": "Lead Project Manager",
                "department": "Project Management",
            },
            {
                "id": "oid-user-002",
                "display_name": "Domas Krupavičius",
                "email": "domas.krupavicius@garantgroup.eu",
                "upn": "domas.krupavicius@garantgroup.eu",
                "job_title": "Senior PM - Ship Repair",
                "department": "Ship Repair",
            },
            {
                "id": "oid-user-003",
                "display_name": "Elena Petrauskienė",
                "email": "elena.petrauskiene@garantgroup.eu",
                "upn": "elena.petrauskiene@garantgroup.eu",
                "job_title": "Project Manager - Marine Systems",
                "department": "Marine Systems",
            },
        ],
    },
    {
        "id": "sg-eng-002",
        "display_name": "Technical & Engineering Specialists",
        "mail": "engineers@garantgroup.eu",
        "description": "Naval architects, electrical and mechanical design engineers",
        "security_enabled": True,
        "members": [
            {
                "id": "oid-user-004",
                "display_name": "Andrius Kazlauskas",
                "email": "andrius.kazlauskas@garantgroup.eu",
                "upn": "andrius.kazlauskas@garantgroup.eu",
                "job_title": "Chief Naval Architect",
                "department": "Engineering",
            },
            {
                "id": "oid-user-005",
                "display_name": "Mindaugas Vaitkus",
                "email": "mindaugas.vaitkus@garantgroup.eu",
                "upn": "mindaugas.vaitkus@garantgroup.eu",
                "job_title": "Senior Electrical Engineer",
                "department": "Electrical & Automation",
            },
            {
                "id": "oid-user-006",
                "display_name": "Lukas Baltrūnas",
                "email": "lukas.baltrunas@garantgroup.eu",
                "upn": "lukas.baltrunas@garantgroup.eu",
                "job_title": "Mechanical Propulsion Specialist",
                "department": "Propulsion",
            },
        ],
    },
    {
        "id": "sg-field-003",
        "display_name": "Yard & Workshop Technicians",
        "mail": "yard-technicians@garantgroup.eu",
        "description": "Workshop hull welders, mechanics and hydraulic technicians",
        "security_enabled": True,
        "members": [
            {
                "id": "oid-user-007",
                "display_name": "Artūras Stankus",
                "email": "arturas.stankus@garantgroup.eu",
                "upn": "arturas.stankus@garantgroup.eu",
                "job_title": "Senior Welder - Hull & Piping",
                "department": "Yard Operations",
            },
            {
                "id": "oid-user-008",
                "display_name": "Giedrius Navickas",
                "email": "giedrius.navickas@garantgroup.eu",
                "upn": "giedrius.navickas@garantgroup.eu",
                "job_title": "Hydraulics Specialist",
                "department": "Field Service",
            },
            {
                "id": "oid-user-009",
                "display_name": "Mantas Paulauskas",
                "email": "mantas.paulauskas@garantgroup.eu",
                "upn": "mantas.paulauskas@garantgroup.eu",
                "job_title": "Machinist & Shaft Alignment Tech",
                "department": "Workshop",
            },
        ],
    },
    {
        "id": "sg-fin-004",
        "display_name": "Finance & Cost Controlling",
        "mail": "finance-controlling@garantgroup.eu",
        "description": "Project Finance Managers and budget controllers",
        "security_enabled": True,
        "members": [
            {
                "id": "oid-user-010",
                "display_name": "Rasa Žukauskienė",
                "email": "rasa.zukauskiene@garantgroup.eu",
                "upn": "rasa.zukauskiene@garantgroup.eu",
                "job_title": "Project Finance Manager",
                "department": "Finance & Accounting",
            },
            {
                "id": "oid-user-011",
                "display_name": "Viktorija Mockutė",
                "email": "viktorija.mockute@garantgroup.eu",
                "upn": "viktorija.mockute@garantgroup.eu",
                "job_title": "Cost Controller",
                "department": "Controlling",
            },
        ],
    },
]


class EntraGraphService:
    @property
    def client_id(self) -> str:
        return settings.AZURE_AD_CLIENT_ID

    @property
    def tenant_id(self) -> str:
        return settings.AZURE_AD_TENANT_ID

    @property
    def client_secret(self) -> str:
        return settings.AZURE_AD_CLIENT_SECRET

    @property
    def is_configured(self) -> bool:
        return bool(self.client_id and self.tenant_id and self.client_secret)

    def _acquire_token(self) -> Optional[str]:
        if not self.is_configured:
            return None
        try:
            import msal
            app = msal.ConfidentialClientApplication(
                client_id=self.client_id,
                client_credential=self.client_secret,
                authority=f"https://login.microsoftonline.com/{self.tenant_id}",
            )
            result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
            if "access_token" in result:
                return result["access_token"]
            err_desc = result.get("error_description", result.get("error", "Unknown MSAL error"))
            logger.error(f"Failed to acquire Microsoft Graph token: {err_desc}")
            return None
        except Exception as e:
            logger.exception(f"Error acquiring MSAL token: {e}")
            return None

    def test_connection(self) -> Dict[str, Any]:
        """
        Tests connection to Microsoft Entra ID and Microsoft Graph.
        Returns connection state, tenant display name, and diagnostic details.
        """
        if not self.is_configured:
            return {
                "connected": False,
                "configured": False,
                "mode": "LOCAL_FALLBACK",
                "message": "Entra ID credentials not configured. Using local demo directory.",
            }

        token = self._acquire_token()
        if not token:
            return {
                "connected": False,
                "configured": True,
                "mode": "ERROR",
                "message": "Authentication failed. Check your Tenant ID, Client ID, and Client Secret in Azure App Registration.",
            }

        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(
                    "https://graph.microsoft.com/v1.0/organization?$select=id,displayName",
                    headers={"Authorization": f"Bearer {token}"},
                )
                if resp.status_code == 200:
                    val = resp.json().get("value", [{}])[0]
                    tenant_name = val.get("displayName") or "Garant Group Entra ID"
                    return {
                        "connected": True,
                        "configured": True,
                        "mode": "LIVE",
                        "tenant_name": tenant_name,
                        "tenant_id": self.tenant_id,
                        "client_id": self.client_id,
                        "message": f"Connected to Microsoft Entra ID ({tenant_name})",
                    }
                else:
                    return {
                        "connected": False,
                        "configured": True,
                        "mode": "ERROR",
                        "message": f"Microsoft Graph error (HTTP {resp.status_code}): {resp.text}",
                    }
        except Exception as e:
            return {
                "connected": False,
                "configured": True,
                "mode": "ERROR",
                "message": f"Connection network error: {str(e)}",
            }


    def search_users(self, query: str, limit: int = 15) -> List[Dict[str, Any]]:
        """
        Searches Entra ID directory users by displayName, email, or userPrincipalName.
        """
        token = self._acquire_token()
        if token:
            try:
                # Microsoft Graph API endpoint
                q = query.replace("'", "''")
                url = (
                    f"https://graph.microsoft.com/v1.0/users?"
                    f"$filter=startswith(displayName,'{q}') or startswith(mail,'{q}') or startswith(userPrincipalName,'{q}')"
                    f"&$select=id,displayName,mail,userPrincipalName,jobTitle,department"
                    f"&$top={limit}"
                )
                with httpx.Client(timeout=8.0) as client:
                    resp = client.get(url, headers={"Authorization": f"Bearer {token}"})
                    if resp.status_code == 200:
                        data = resp.json().get("value", [])
                        return [
                            {
                                "id": u.get("id"),
                                "display_name": u.get("displayName") or u.get("mail") or "Unknown",
                                "email": u.get("mail") or u.get("userPrincipalName", ""),
                                "upn": u.get("userPrincipalName", ""),
                                "job_title": u.get("jobTitle") or "",
                                "department": u.get("department") or "",
                            }
                            for u in data
                        ]
                    logger.warning(f"Graph users search returned {resp.status_code}: {resp.text}")
            except Exception as e:
                logger.exception(f"Error calling Microsoft Graph users search: {e}")

        # Fallback to mock organizational directory
        q_lower = query.lower().strip()
        matched: List[Dict[str, Any]] = []
        for g in MOCK_SECURITY_GROUPS:
            for m in g["members"]:
                if (
                    q_lower in m["display_name"].lower()
                    or q_lower in m["email"].lower()
                    or q_lower in m["upn"].lower()
                    or (m.get("department") and q_lower in m["department"].lower())
                ):
                    if not any(x["email"] == m["email"] for x in matched):
                        matched.append(m)

        # If user searched a direct email not in mock directory, provide a structured candidate
        if "@" in q_lower and not any(x["email"].lower() == q_lower for x in matched):
            prefix = q_lower.split("@")[0].replace(".", " ").title()
            matched.append({
                "id": f"oid-{abs(hash(q_lower)) % 1000000:06d}",
                "display_name": prefix,
                "email": q_lower,
                "upn": q_lower,
                "job_title": "Specialist",
                "department": "Operations",
            })

        return matched[:limit]

    def get_user_by_email(self, email_or_upn: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves a single user by email or userPrincipalName.
        """
        token = self._acquire_token()
        if token:
            try:
                import urllib.parse
                safe_email = urllib.parse.quote(email_or_upn)
                url = (
                    f"https://graph.microsoft.com/v1.0/users/{safe_email}?"
                    f"$select=id,displayName,mail,userPrincipalName,jobTitle,department"
                )
                with httpx.Client(timeout=8.0) as client:
                    resp = client.get(url, headers={"Authorization": f"Bearer {token}"})
                    if resp.status_code == 200:
                        u = resp.json()
                        return {
                            "id": u.get("id"),
                            "display_name": u.get("displayName") or u.get("mail") or "Unknown",
                            "email": u.get("mail") or u.get("userPrincipalName", ""),
                            "upn": u.get("userPrincipalName", ""),
                            "job_title": u.get("jobTitle") or "",
                            "department": u.get("department") or "",
                        }
            except Exception as e:
                logger.exception(f"Error fetching user by email from Microsoft Graph: {e}")

        # Fallback to mock directory
        e_lower = email_or_upn.lower().strip()
        for g in MOCK_SECURITY_GROUPS:
            for m in g["members"]:
                if m["email"].lower() == e_lower or m["upn"].lower() == e_lower:
                    return m

        # If valid email format, synthesize user info
        if "@" in e_lower:
            prefix = e_lower.split("@")[0].replace(".", " ").title()
            return {
                "id": f"oid-{abs(hash(e_lower)) % 1000000:06d}",
                "display_name": prefix,
                "email": e_lower,
                "upn": e_lower,
                "job_title": "Staff Specialist",
                "department": "Operations",
            }
        return None

    def search_security_groups(self, query: str = "", limit: int = 50) -> List[Dict[str, Any]]:
        """
        Searches Entra ID security groups and Microsoft 365 groups.
        Supports lookup by group name, email, or direct Group Object ID (GUID).
        """
        token = self._acquire_token()
        if token:
            try:
                q = query.replace("'", "''").strip()
                import uuid
                is_guid = False
                try:
                    uuid.UUID(q)
                    is_guid = True
                except Exception:
                    pass

                # If a direct Object ID GUID is provided, query directly
                if is_guid:
                    url = f"https://graph.microsoft.com/v1.0/groups/{q}?$select=id,displayName,mail,description,securityEnabled"
                    with httpx.Client(timeout=10.0) as client:
                        resp = client.get(url, headers={"Authorization": f"Bearer {token}"})
                        if resp.status_code == 200:
                            g = resp.json()
                            return [{
                                "id": g.get("id"),
                                "display_name": g.get("displayName") or "Group",
                                "mail": g.get("mail") or "",
                                "description": g.get("description") or "",
                                "security_enabled": g.get("securityEnabled", True),
                                "members_count": 0,
                            }]

                # Otherwise query groups list (including both security groups & M365 groups)
                if q:
                    filter_clause = f"startswith(displayName,'{q}') or startswith(mail,'{q}')"
                    url = f"https://graph.microsoft.com/v1.0/groups?$filter={filter_clause}&$select=id,displayName,mail,description,securityEnabled&$top={limit}"
                else:
                    url = f"https://graph.microsoft.com/v1.0/groups?$select=id,displayName,mail,description,securityEnabled&$top={limit}"

                with httpx.Client(timeout=10.0) as client:
                    resp = client.get(url, headers={"Authorization": f"Bearer {token}"})
                    if resp.status_code == 200:
                        data = resp.json().get("value", [])
                        return [
                            {
                                "id": g.get("id"),
                                "display_name": g.get("displayName") or "Unnamed Group",
                                "mail": g.get("mail") or "",
                                "description": g.get("description") or "",
                                "security_enabled": g.get("securityEnabled", True),
                                "members_count": 0,
                            }
                            for g in data
                        ]
                    else:
                        logger.warning(f"Graph groups query returned {resp.status_code}: {resp.text}")
            except Exception as e:
                logger.exception(f"Error searching security groups from Microsoft Graph: {e}")

        # Fallback to mock security groups
        q_lower = query.lower().strip()
        results = []
        for g in MOCK_SECURITY_GROUPS:
            if not q_lower or q_lower in g["display_name"].lower() or (g["mail"] and q_lower in g["mail"].lower()) or g["id"] == q_lower:
                results.append({
                    "id": g["id"],
                    "display_name": g["display_name"],
                    "mail": g["mail"],
                    "description": g["description"],
                    "security_enabled": g["security_enabled"],
                    "members_count": len(g["members"]),
                })
        return results

    def get_group_members(self, group_id: str) -> List[Dict[str, Any]]:
        """
        Retrieves user members of an Entra ID security group.
        Uses /transitiveMembers (including nested groups) with fallback to /members.
        """
        token = self._acquire_token()
        if token:
            try:
                url = (
                    f"https://graph.microsoft.com/v1.0/groups/{group_id}/transitiveMembers"
                    f"?$select=id,displayName,mail,userPrincipalName,jobTitle,department"
                )
                with httpx.Client(timeout=12.0) as client:
                    resp = client.get(url, headers={"Authorization": f"Bearer {token}"})
                    if resp.status_code != 200:
                        # Fallback to direct members
                        url = f"https://graph.microsoft.com/v1.0/groups/{group_id}/members?$select=id,displayName,mail,userPrincipalName,jobTitle,department"
                        resp = client.get(url, headers={"Authorization": f"Bearer {token}"})

                    if resp.status_code == 200:
                        data = resp.json().get("value", [])
                        return [
                            {
                                "id": u.get("id"),
                                "display_name": u.get("displayName") or u.get("mail") or "Unknown",
                                "email": u.get("mail") or u.get("userPrincipalName", ""),
                                "upn": u.get("userPrincipalName", ""),
                                "job_title": u.get("jobTitle") or "",
                                "department": u.get("department") or "",
                            }
                            for u in data
                            if "@" in (u.get("mail") or u.get("userPrincipalName", ""))
                        ]
            except Exception as e:
                logger.exception(f"Error fetching group members from Microsoft Graph: {e}")

        # Fallback to mock groups
        for g in MOCK_SECURITY_GROUPS:
            if g["id"] == group_id:
                return g["members"]
        return []


entra_graph_service = EntraGraphService()

