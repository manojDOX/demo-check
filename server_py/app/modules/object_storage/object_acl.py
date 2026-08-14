"""Port of server/replit_integrations/object_storage/objectAcl.ts.

Object ACL policies are stored as a JSON blob in the GCS object's custom metadata
under the key "custom:aclPolicy". No access-group types are implemented on the
Node side either (the `ObjectAccessGroupType` enum there is empty) — this is
ported 1:1, including the "unimplemented access group" failure mode.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from google.cloud.storage import Blob

ACL_POLICY_METADATA_KEY = "custom:aclPolicy"


class ObjectPermission(str, Enum):
    READ = "read"
    WRITE = "write"


@dataclass
class ObjectAccessGroup:
    type: str
    id: str


@dataclass
class ObjectAclRule:
    group: ObjectAccessGroup
    permission: ObjectPermission


@dataclass
class ObjectAclPolicy:
    owner: str
    visibility: str  # "public" | "private"
    acl_rules: list[ObjectAclRule] = field(default_factory=list)


def _is_permission_allowed(requested: ObjectPermission, granted: ObjectPermission) -> bool:
    if requested == ObjectPermission.READ:
        return granted in (ObjectPermission.READ, ObjectPermission.WRITE)
    return granted == ObjectPermission.WRITE


def _create_object_access_group(group: ObjectAccessGroup):
    # Mirrors the TS `createObjectAccessGroup`: no group types are implemented yet,
    # so any rule referencing one is a hard error rather than a silent deny.
    raise ValueError(f"Unknown access group type: {group.type}")


def set_object_acl_policy(blob: Blob, acl_policy: ObjectAclPolicy) -> None:
    if not blob.exists():
        raise ValueError(f"Object not found: {blob.name}")

    policy_dict: dict[str, Any] = {
        "owner": acl_policy.owner,
        "visibility": acl_policy.visibility,
        "aclRules": [
            {"group": {"type": r.group.type, "id": r.group.id}, "permission": r.permission.value}
            for r in acl_policy.acl_rules
        ],
    }
    import json

    blob.metadata = {ACL_POLICY_METADATA_KEY: json.dumps(policy_dict)}
    blob.patch()


def get_object_acl_policy(blob: Blob) -> ObjectAclPolicy | None:
    blob.reload()
    metadata = blob.metadata or {}
    raw = metadata.get(ACL_POLICY_METADATA_KEY)
    if not raw:
        return None
    import json

    data = json.loads(raw)
    rules = [
        ObjectAclRule(
            group=ObjectAccessGroup(type=r["group"]["type"], id=r["group"]["id"]),
            permission=ObjectPermission(r["permission"]),
        )
        for r in data.get("aclRules", [])
    ]
    return ObjectAclPolicy(owner=data["owner"], visibility=data["visibility"], acl_rules=rules)


def can_access_object(
    *, user_id: str | None, blob: Blob, requested_permission: ObjectPermission = ObjectPermission.READ
) -> bool:
    acl_policy = get_object_acl_policy(blob)
    if acl_policy is None:
        return False

    if acl_policy.visibility == "public" and requested_permission == ObjectPermission.READ:
        return True

    if not user_id:
        return False

    if acl_policy.owner == user_id:
        return True

    for rule in acl_policy.acl_rules:
        group = _create_object_access_group(rule.group)  # always raises today, matching TS
        if group and _is_permission_allowed(requested_permission, rule.permission):
            return True

    return False
