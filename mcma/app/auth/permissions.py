"""
mcma.app.auth.permissions -- the role -> permission map (INC-16,
DATA_MODEL.md §2's role_permissions table). The Permission enum itself
already exists in mcma.domain.enums (INC-04, DOMAIN_MODEL §2) -- this
module only adds the role map, never redefines the enum.
"""

from __future__ import annotations

from mcma.domain.enums import Permission

ROLE_PERMISSIONS: dict[str, frozenset] = {
    "admin": frozenset(Permission),
    "operator": frozenset(
        {
            Permission.NOTIFICATIONS_READ,
            Permission.NOTIFICATIONS_UPDATE,
            Permission.JOBS_PLAN,
            Permission.JOBS_EXECUTE,
            Permission.JOBS_VIEW,
        }
    ),
    "viewer": frozenset({Permission.NOTIFICATIONS_READ, Permission.JOBS_VIEW}),
}


def permissions_for_role(role: str) -> frozenset:
    return ROLE_PERMISSIONS.get(role, frozenset())


def role_has_permission(role: str, permission: Permission) -> bool:
    return permission in permissions_for_role(role)
