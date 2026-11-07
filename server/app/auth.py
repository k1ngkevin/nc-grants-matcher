"""Authorization behind Azure Container Apps built-in authentication.

Identity headers are trusted ONLY behind Easy Auth, which strips client-supplied
headers. Never expose the container port through another ingress in this mode.
"""
import base64
import binascii
import json
import os
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, Request

from . import config
from .agencies import AGENCY_BY_ID
from .public_subscriptions import is_public


@dataclass(frozen=True)
class Identity:
    object_id: str
    name: str
    roles: frozenset[str]

    @property
    def admin(self):
        return "Matchmaker.Admin" in self.roles

    def allows(self, agency_id):
        return self.admin or f"Agency.{agency_id}" in self.roles


def validate_config():
    if config.AUTH_MODE not in {"development", "entra"}:
        raise RuntimeError("AUTH_MODE must be development or entra")
    if config.AUTH_MODE == "development":
        if os.getenv("CONTAINER_APP_NAME") or config.APP_ENV == "production":
            raise RuntimeError("Production requires AUTH_MODE=entra")
        return
    if not os.getenv("CONTAINER_APP_NAME"):
        raise RuntimeError("Entra header authentication requires Azure Container Apps Easy Auth")
    try:
        UUID(config.ENTRA_TENANT_ID)
    except ValueError:
        raise RuntimeError("ENTRA_TENANT_ID must be the approved tenant UUID") from None
    if not config.PUBLIC_BASE_URL.startswith("https://"):
        raise RuntimeError("Entra authentication requires an HTTPS PUBLIC_BASE_URL")


def identity_from_headers(request: Request) -> Identity:
    """Read claims authenticated and injected by the Container Apps sidecar."""
    raw = request.headers.get("x-ms-client-principal", "")
    if not raw:
        raise HTTPException(401, "Sign in with your approved work account.")
    try:
        if len(raw) > 65536:
            raise ValueError()
        principal = json.loads(base64.b64decode(raw, validate=True))
        if principal.get("auth_typ") != "aad":
            raise ValueError()
        claims = principal["claims"]
        values = {}
        for claim in claims:
            values.setdefault(claim["typ"], set()).add(claim["val"])
        tenants = values.get("http://schemas.microsoft.com/identity/claims/tenantid", set()) | values.get("tid", set())
        if tenants != {config.ENTRA_TENANT_ID}:
            raise HTTPException(403, "Your organization is not authorized.")
        ids = values.get("http://schemas.microsoft.com/identity/claims/objectidentifier", set()) | values.get("oid", set())
        if len(ids) != 1:
            raise ValueError()
        object_id = str(UUID(next(iter(ids))))
        roles = frozenset(values.get("roles", set()) | values.get("http://schemas.microsoft.com/ws/2008/06/identity/claims/role", set()))
    except (ValueError, TypeError, KeyError, AttributeError, binascii.Error):
        raise HTTPException(401, "Invalid sign-in identity.") from None
    identity = Identity(object_id, request.headers.get("x-ms-client-principal-name", object_id), roles)
    if not identity.admin and not any(identity.allows(a) for a in AGENCY_BY_ID):
        raise HTTPException(403, "Ask your administrator to assign an agency access role.")
    return identity


async def authorize_agency(request: Request):
    """Global dependency: every current agency body/path is checked server-side."""
    if config.AUTH_MODE == "development" or is_public(request):
        return
    identity = request.state.identity
    if request.url.path in {"/api/metrics", "/api/admin/ingest"} and not identity.admin:
        raise HTTPException(403, "Administrator access required.")
    agency_ids = [request.path_params.get("agency_id")]
    if request.method == "POST" and request.headers.get("content-type", "").split(";")[0] == "application/json":
        try:
            body = await request.json()
        except ValueError:
            return  # FastAPI supplies the validation error.
        if isinstance(body, dict):
            agency_ids.append(body.get("agency_id"))
    if request.url.path in {"/api/subscriptions/confirm", "/api/subscriptions/unsubscribe"}:
        from . import emailer
        sub = emailer.find_subscription(request.query_params.get("token", ""))
        if sub:
            agency_ids.append(sub["agency_id"])
    for agency_id in agency_ids:
        if agency_id is not None and (not isinstance(agency_id, str) or not identity.allows(agency_id)):
            raise HTTPException(403, "You do not have access to this agency.")
