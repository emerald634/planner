"""Pure decisions, not login/password verification or an HTTP visit protocol."""
from dataclasses import replace

from .models import (Credential, CredentialState, Employee, PasswordAction,
                     Purpose, Role, Session, Visit, VISIT_LIFETIME, integer)


def login_allowed(employee: Employee, credential: Credential) -> bool:
    return (employee.active and credential.active
            and credential.employee_id == employee.id
            and credential.state == CredentialState.READY)


def session_allowed(employee: Employee, credential: Credential, session: Session, *, now: int) -> bool:
    integer(now)
    return (login_allowed(employee, credential)
            and session.credential_id == credential.id
            and session.credential_version == credential.version
            and session.revoked_at is None
            and session.issued_at <= session.last_visited_at <= now
            and now < session.absolute_expires_at
            and now - session.last_visited_at < VISIT_LIFETIME)


def record_visit(employee: Employee, credential: Credential, session: Session,
                 event: Visit, *, now: int) -> Session:
    if not isinstance(event, Visit):
        raise ValueError("Unknown visit event")
    if not session_allowed(employee, credential, session, now=now):
        raise PermissionError("Session unavailable")
    return replace(session, last_visited_at=now) if event == Visit.FOREGROUND else session


def can_access(employee: Employee, owner_id: int) -> bool:
    integer(owner_id, 1)
    return employee.active and (employee.role == Role.SUPERVISOR or employee.id == owner_id)


def can_manage_account(supervisor: Employee, target: Employee, *, password_reconfirmed: bool) -> bool:
    # This flag is a policy input, never a replacement for a password verifier.
    if type(password_reconfirmed) is not bool:
        raise ValueError("Invalid reauthentication result")
    return (supervisor.active and supervisor.role == Role.SUPERVISOR
            and target.active and target.role == Role.MANAGER and password_reconfirmed)


def action_allowed(employee: Employee, credential: Credential, action: PasswordAction,
                   purpose: Purpose, *, now: int) -> bool:
    integer(now)
    if not isinstance(purpose, Purpose):
        raise ValueError("Unknown purpose")
    required = CredentialState.RESET_PENDING if purpose == Purpose.RESET else CredentialState.INVITED
    return (employee.active and credential.active and employee.id == credential.employee_id
            and credential.state == required and action.purpose == purpose
            and action.credential_id == credential.id
            and action.credential_version == credential.version
            and action.used_at is None and action.revoked_at is None
            and action.issued_at <= now < action.expires_at)


def begin_reset(credential: Credential) -> Credential:
    """Proposed state transition only; caller must atomically revoke sessions/codes."""
    return replace(credential, state=CredentialState.RESET_PENDING,
                   version=credential.version + 1, password_hash=None)


def complete_reset(employee: Employee, credential: Credential, action: PasswordAction,
                   *, new_password_hash: str, now: int) -> tuple[Credential, PasswordAction]:
    """Opaque hash supplied by future verifier layer; never accepts/checks a password."""
    if not action_allowed(employee, credential, action, Purpose.RESET, now=now):
        raise PermissionError("Reset unavailable")
    return (replace(credential, state=CredentialState.READY, version=credential.version + 1,
                    password_hash=new_password_hash), replace(action, used_at=now))
