# Employee administration

Open `/admin/employees` while signed in as a Django superuser or a CRM user with role `super_admin`. The sidebar link is **Employee admin**. The existing `admin` superuser has access without changing its stored role or password. Management, branch managers and other staff cannot access these APIs.

The panel supports a searchable employee directory, branch/role/active filters, account creation, editing, deactivation/reactivation, routing capacity and readiness, password reset, role descriptions and access history. No employee deletion is offered: historical ownership and audit records must remain intact.

Roles:

| Role | Scope | Main access |
|---|---|---|
| Intern | Assigned branch | Read-only CRM; no sales writes, routing, inbox or chat-history access |
| Counsellor | Assigned branch | Existing sales-owner workflows and shared inbox |
| Manager (`branch_manager`) | Assigned branch | Assignments, branch operations, counsellors and team reports |
| Admin (`super_admin`) | All branches | CRM operations and employee administration |
| Management | All branches | Operations without employee administration |
| Accounts | Assigned branch | Existing read-only CRM access |
| Support | Assigned branch | Existing CRM reading and shared WhatsApp support |

CRM Admin does not set Django `is_superuser`, `is_staff`, groups or model permissions. These fields are never writable through the panel. Protected system accounts cannot have their access changed here; a non-system CRM Admin cannot edit or reset another system account. Administrators cannot deactivate, demote or change the branch of their own account. Administrative writes serialize and re-check the acting administrator after acquiring the lock to prevent stale concurrent privileges.

New employees start outside automatic assignment unless explicitly enabled. Only active counsellors/managers with an active branch can receive leads. Role/branch removal or deactivation is blocked while the employee owns active enquiries; reassign those using existing routing controls first. On permitted access changes, sessions are revoked and open standalone automation/demo work returns to the manager queue. Existing scheduler rules handle subsequent assignment. No historical enquiry is silently transferred by employee editing.

Initial passwords and resets use Django password validators (at least 12 characters) and `set_password`. No password/hash is returned by the API, stored in access events or emailed. Deliver chosen passwords privately. Self password change additionally requires the current password. Password reset invalidates existing session authentication hashes; a self-change preserves the current authenticated session. Role, branch or active-state changes also delete the employee's current stored sessions so reactivation does not restore previous sessions. Other users' sessions remain unchanged.

API endpoints: `/api/v1/admin/employees/`, `/admin/employees/summary/`, `/admin/employees/{id}/` (PATCH), `/admin/employees/{id}/reset-password/` (POST), `/admin/access-events/` (read-only). Session-authenticated writes retain the existing CSRF requirement. Usernames are checked case-insensitively inside the administration transaction. Access events record the administrator, target, action, time and non-secret changes.

Apply `accounts.0002_alter_user_role_useraccessevent` before using the panel. No real employee accounts, password resets or privilege grants are performed automatically by installing this feature. Google Contacts, external notifications and mandatory first-login password changes are not part of this change.
