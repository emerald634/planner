"""Immutable policy inputs; callers must load current employee/credential rows.

These objects are not authentication proofs. No password verification occurs here.
"""
from dataclasses import dataclass, field
from enum import StrEnum

DAY = 86400
SESSION_LIFETIME = 90 * DAY
VISIT_LIFETIME = 30 * DAY
RESET_LIFETIME = 30 * 60


def integer(value, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError("Invalid integer")


class Role(StrEnum):
    MANAGER = "manager"
    SUPERVISOR = "supervisor"


class CredentialState(StrEnum):
    INVITED = "invited"
    READY = "ready"
    RESET_PENDING = "reset_pending"


class Purpose(StrEnum):
    INVITATION = "invitation"
    RESET = "reset"


class Visit(StrEnum):
    FOREGROUND = "foreground"
    BACKGROUND = "background"


@dataclass(frozen=True)
class Employee:
    id: int
    role: Role
    active: bool

    def __post_init__(self):
        integer(self.id, 1)
        if not isinstance(self.role, Role) or type(self.active) is not bool:
            raise ValueError("Invalid employee")


@dataclass(frozen=True)
class Credential:
    id: int
    employee_id: int
    active: bool
    state: CredentialState
    version: int
    password_hash: str | None = field(default=None, repr=False)

    def __post_init__(self):
        for value in (self.id, self.employee_id, self.version):
            integer(value, 1)
        if type(self.active) is not bool or not isinstance(self.state, CredentialState):
            raise ValueError("Invalid credential")
        if self.password_hash is not None and (not isinstance(self.password_hash, str) or not self.password_hash):
            raise ValueError("Invalid opaque password hash")
        if self.state == CredentialState.READY and not self.password_hash:
            raise ValueError("Ready credential needs an opaque hash")
        if self.state != CredentialState.READY and self.password_hash is not None:
            raise ValueError("Pending credential cannot retain a password hash")


@dataclass(frozen=True)
class Session:
    credential_id: int
    credential_version: int
    issued_at: int
    last_visited_at: int
    absolute_expires_at: int
    revoked_at: int | None = None

    def __post_init__(self):
        integer(self.credential_id, 1)
        integer(self.credential_version, 1)
        for value in (self.issued_at, self.last_visited_at, self.absolute_expires_at):
            integer(value)
        if not self.issued_at <= self.last_visited_at < self.absolute_expires_at:
            raise ValueError("Invalid session timeline")
        if self.absolute_expires_at != self.issued_at + SESSION_LIFETIME:
            raise ValueError("Invalid absolute lifetime")
        if self.revoked_at is not None:
            integer(self.revoked_at, self.issued_at)


@dataclass(frozen=True)
class PasswordAction:
    credential_id: int
    credential_version: int
    purpose: Purpose
    issued_by: int
    issued_at: int
    expires_at: int
    used_at: int | None = None
    revoked_at: int | None = None

    def __post_init__(self):
        for value in (self.credential_id, self.credential_version, self.issued_by):
            integer(value, 1)
        integer(self.issued_at)
        integer(self.expires_at, self.issued_at + 1)
        if not isinstance(self.purpose, Purpose):
            raise ValueError("Invalid action purpose")
        if self.purpose == Purpose.RESET and self.expires_at != self.issued_at + RESET_LIFETIME:
            raise ValueError("Invalid reset lifetime")
        for value in (self.used_at, self.revoked_at):
            if value is not None:
                integer(value, self.issued_at)
        if self.used_at is not None and self.used_at >= self.expires_at:
            raise ValueError("Action consumed after expiry")
