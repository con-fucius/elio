"""Permission codes and role bundles. Server is authoritative."""

from __future__ import annotations

from enum import StrEnum


class PermissionCode(StrEnum):
    TENANT_ADMIN = "tenant.admin"
    ORG_ADMIN = "org.admin"
    ACTOR_READ = "actor.read"
    ACTOR_MANAGE = "actor.manage"
    WORK_ITEM_CREATE = "work_item.create"
    WORK_ITEM_READ = "work_item.read"
    WORK_ITEM_ASSIGN = "work_item.assign"
    WORK_ITEM_ACCEPT = "work_item.accept"
    WORK_ITEM_EXECUTE = "work_item.execute"
    WORK_ITEM_SUBMIT = "work_item.submit"
    WORK_ITEM_EXCEPTION = "work_item.exception"
    WORK_ITEM_REVIEW = "work_item.review"
    WORK_ITEM_CANCEL = "work_item.cancel"
    WORK_ITEM_WITHDRAW = "work_item.withdraw"
    TEMPLATE_READ = "template.read"
    TEMPLATE_MANAGE = "template.manage"


ALL_PERMISSIONS: frozenset[str] = frozenset(p.value for p in PermissionCode)

# Default tenant role bundles. Seeded when a tenant is provisioned.
ROLE_BUNDLES: dict[str, frozenset[str]] = {
    "field_worker": frozenset(
        {
            PermissionCode.WORK_ITEM_READ.value,
            PermissionCode.WORK_ITEM_ACCEPT.value,
            PermissionCode.WORK_ITEM_EXECUTE.value,
            PermissionCode.WORK_ITEM_SUBMIT.value,
            PermissionCode.WORK_ITEM_EXCEPTION.value,
            PermissionCode.WORK_ITEM_WITHDRAW.value,
            PermissionCode.TEMPLATE_READ.value,
        }
    ),
    "supervisor": frozenset(
        {
            PermissionCode.WORK_ITEM_READ.value,
            PermissionCode.WORK_ITEM_CREATE.value,
            PermissionCode.WORK_ITEM_ASSIGN.value,
            PermissionCode.WORK_ITEM_EXECUTE.value,
            PermissionCode.WORK_ITEM_EXCEPTION.value,
            PermissionCode.WORK_ITEM_REVIEW.value,
            PermissionCode.WORK_ITEM_CANCEL.value,
            PermissionCode.ACTOR_READ.value,
            PermissionCode.TEMPLATE_READ.value,
            PermissionCode.TEMPLATE_MANAGE.value,
        }
    ),
    "operations_manager": frozenset(
        {
            PermissionCode.WORK_ITEM_READ.value,
            PermissionCode.WORK_ITEM_CREATE.value,
            PermissionCode.WORK_ITEM_ASSIGN.value,
            PermissionCode.WORK_ITEM_REVIEW.value,
            PermissionCode.WORK_ITEM_CANCEL.value,
            PermissionCode.ACTOR_READ.value,
            PermissionCode.ORG_ADMIN.value,
            PermissionCode.TEMPLATE_READ.value,
            PermissionCode.TEMPLATE_MANAGE.value,
        }
    ),
    "compliance_auditor": frozenset(
        {
            PermissionCode.WORK_ITEM_READ.value,
            PermissionCode.ACTOR_READ.value,
        }
    ),
}
