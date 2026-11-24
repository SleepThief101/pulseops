# Organization Membership and Role-Based Authorization

PulseOps uses multi-tenant role-based access control (RBAC) to restrict organization actions according to the authenticated user's role in the organization.

---

## Roles and Hierarchy

Every member of an organization is assigned exactly one role:

| Role | Hierarchy Level | Capabilities |
| :--- | :---: | :--- |
| `owner` | 3 | Full administrative privileges, manage members, billing, settings. |
| `member` | 2 | Standard operational access (read, write integrations/metrics). |
| `viewer` | 1 | Read-only access to organization resources. |

Hierarchy rule: An action requiring role $R$ permits any member holding role $M$ where $\text{Level}(M) \ge \text{Level}(R)$.
- Requiring `owner` allows only `owner`.
- Requiring `member` allows `owner` and `member`.
- Requiring `viewer` allows `owner`, `member`, and `viewer`.

---

## Authorization Dependencies

### `get_current_membership(org_id: uuid.UUID)`
Extracts the authenticated user via `get_current_user` and checks whether the user belongs to `org_id`.
- Returns the `Membership` record on success.
- Returns `HTTP 404 Not Found` if the user is not a member of the organization.
- **Security Rule:** Never reveals whether an organization ID exists to unauthorized users. Both non-existent organizations and organizations where the requester is not a member return identical `404 Not Found` responses.

### `require_role(required_role: str | MembershipRole)`
A reusable dependency factory enforcing role permissions:
```python
@router.post("/orgs/{org_id}/members", ...)
def add_member(
    org_id: uuid.UUID,
    payload: AddMemberRequest,
    membership: Membership = Depends(require_role("owner")),
):
    ...
```
- First invokes `get_current_membership(org_id)` (returns 404 if not in org).
- Checks `ROLE_HIERARCHY[membership.role] >= ROLE_HIERARCHY[required_role]`.
- Returns `HTTP 403 Forbidden` (`{"detail": "Insufficient permissions for this organization."}`) if the member lacks the required role.

---

## Endpoints

### 1. Add Organization Member
**`POST /orgs/{org_id}/members`**

Adds an existing user to the organization. Restricted to **owners**.

**Request Body:**
```json
{
  "email": "teammate@example.com",
  "role": "member"
}
```
- `email`: Required valid email address of an existing registered user.
- `role`: Optional, defaults to `"member"`. Must be `"owner"`, `"member"`, or `"viewer"`.

**Success Response (`201 Created`):**
```json
{
  "id": "e4b3e64f-7e23-4f24-9b8e-324f2b1d6e89",
  "user_id": "f5c2d3e1-8a9b-4c5d-6e7f-8a9b0c1d2e3f",
  "organization_id": "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",
  "role": "member",
  "created_at": "2026-11-24T20:00:00Z",
  "email": "teammate@example.com",
  "user": {
    "id": "f5c2d3e1-8a9b-4c5d-6e7f-8a9b0c1d2e3f",
    "email": "teammate@example.com",
    "created_at": "2026-11-24T18:00:00Z"
  }
}
```

**Errors:**
- `401 Unauthorized`: Missing or invalid Bearer token.
- `403 Forbidden`: Requester is a member or viewer, not an owner.
- `404 Not Found`: Requester is not in the organization, or target user email does not exist.
- `409 Conflict`: Target user is already a member of this organization.
- `422 Unprocessable Entity`: Malformed email or invalid role.

---

### 2. List Organization Members
**`GET /orgs/{org_id}/members`**

Lists all members of the organization. Permitted for **any active member** (`owner`, `member`, `viewer`).

**Success Response (`200 OK`):**
```json
[
  {
    "id": "e4b3e64f-7e23-4f24-9b8e-324f2b1d6e89",
    "user_id": "f5c2d3e1-8a9b-4c5d-6e7f-8a9b0c1d2e3f",
    "organization_id": "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",
    "role": "owner",
    "created_at": "2026-11-24T19:00:00Z",
    "email": "founder@example.com",
    "user": {
      "id": "f5c2d3e1-8a9b-4c5d-6e7f-8a9b0c1d2e3f",
      "email": "founder@example.com",
      "created_at": "2026-11-24T18:00:00Z"
    }
  }
]
```

**Errors:**
- `401 Unauthorized`: Missing or invalid Bearer token.
- `404 Not Found`: Requester is not a member of the organization.

---

## Security Guarantees

1. **Information Leakage Prevention (404 Obscurity):** Unauthenticated or unauthorized inquiries regarding organization existence always return 404.
2. **Zero Credential Exposure:** `password_hash`, Fernet keys, and JWT secrets are strictly excluded from response schemas.
3. **Atomic Enforcement:** Database constraints (`uq_memberships_user_org`) and session commits guard against duplicate membership race conditions.
