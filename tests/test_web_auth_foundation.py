"""Pure policy/state tests. No password verifier, HTTP auth or visit protocol."""
import unittest
from dataclasses import FrozenInstanceError, replace

from planner.web_auth.models import (Credential, CredentialState, Employee, PasswordAction,
                                     Purpose, Role, Session, Visit, DAY, SESSION_LIFETIME)
from planner.web_auth.policy import (action_allowed, begin_reset, can_access,
                                     can_manage_account, complete_reset, login_allowed,
                                     record_visit, session_allowed)


class FoundationPolicyTests(unittest.TestCase):
    def setUp(self):
        self.employee = Employee(1, Role.MANAGER, True)
        self.supervisor = Employee(3, Role.SUPERVISOR, True)
        self.credential = Credential(1, 1, True, CredentialState.READY, 1, "opaque-test-marker")
        self.session = Session(1, 1, 100, 100, 100 + SESSION_LIFETIME)

    def test_web_identity_has_no_telegram_acl_or_admin_role(self):
        self.assertTrue(login_allowed(self.employee, self.credential))
        self.assertFalse(can_access(self.employee, 2))
        self.assertTrue(can_access(self.employee, 1))
        self.assertTrue(can_access(self.supervisor, 2))
        self.assertFalse(can_manage_account(self.employee, self.employee, password_reconfirmed=True))

    def test_current_employee_and_credential_activity_and_binding(self):
        for emp, cred in ((replace(self.employee, active=False), self.credential),
                          (self.employee, replace(self.credential, active=False)),
                          (self.employee, replace(self.credential, employee_id=2))):
            with self.subTest(employee=emp, credential=cred):
                self.assertFalse(login_allowed(emp, cred))
                self.assertFalse(session_allowed(emp, cred, self.session, now=100))
        self.assertTrue(self.employee.active)  # disabling web does not change employee/Telegram

    def test_current_role_changes_permissions_without_session_role_cache(self):
        promoted = replace(self.employee, role=Role.SUPERVISOR)
        self.assertTrue(can_access(promoted, 2))
        self.assertFalse(can_access(replace(promoted, role=Role.MANAGER), 2))
        self.assertFalse(can_access(replace(promoted, active=False), 2))

    def test_supervisor_scope_and_reauthentication(self):
        self.assertTrue(can_manage_account(self.supervisor, self.employee, password_reconfirmed=True))
        for actor, target, reauth in ((self.supervisor, self.employee, False),
                                      (self.supervisor, self.supervisor, True),
                                      (replace(self.supervisor, active=False), self.employee, True),
                                      (self.supervisor, replace(self.employee, active=False), True)):
            self.assertFalse(can_manage_account(actor, target, password_reconfirmed=reauth))
        with self.assertRaises(ValueError):
            can_manage_account(self.supervisor, self.employee, password_reconfirmed="true")

    def test_absolute_90_day_boundary_and_visit_cannot_extend_it(self):
        session = replace(self.session, last_visited_at=100 + 89 * DAY)
        self.assertTrue(session_allowed(self.employee, self.credential, session, now=100 + 90*DAY-1))
        for now in (100+90*DAY, 100+90*DAY+1):
            self.assertFalse(session_allowed(self.employee, self.credential, session, now=now))
        visited = record_visit(self.employee, self.credential, session, Visit.FOREGROUND, now=100+89*DAY+1)
        self.assertEqual(visited.absolute_expires_at, self.session.absolute_expires_at)

    def test_30_day_boundary_short_idle_and_background(self):
        for delay in (1801, DAY, 30*DAY-1):
            self.assertTrue(session_allowed(self.employee, self.credential, self.session, now=100+delay))
        self.assertFalse(session_allowed(self.employee, self.credential, self.session, now=100+30*DAY))
        unchanged = record_visit(self.employee, self.credential, self.session, Visit.BACKGROUND, now=100+DAY)
        self.assertIs(unchanged, self.session)
        visited = record_visit(self.employee, self.credential, self.session, Visit.FOREGROUND, now=100+DAY)
        self.assertEqual(visited.last_visited_at, 100+DAY)
        with self.assertRaises(PermissionError):
            record_visit(self.employee, self.credential, self.session, Visit.FOREGROUND, now=100+30*DAY)
        with self.assertRaises(ValueError):
            record_visit(self.employee, self.credential, self.session, "foreground", now=101)

    def test_revocation_version_binding_and_future_timestamps_fail_closed(self):
        for session in (replace(self.session, revoked_at=101),
                        replace(self.session, credential_version=2),
                        replace(self.session, credential_id=2),
                        replace(self.session, last_visited_at=102)):
            self.assertFalse(session_allowed(self.employee, self.credential, session, now=101))
        self.assertFalse(session_allowed(self.employee, self.credential, self.session, now=99))

    def test_reset_pending_invalidates_hash_sessions_and_expiry_does_not_restore_login(self):
        pending = begin_reset(self.credential)
        self.assertIsNone(pending.password_hash)
        self.assertEqual(pending.version, 2)
        self.assertFalse(login_allowed(self.employee, pending))
        self.assertFalse(session_allowed(self.employee, pending, self.session, now=101))
        action = PasswordAction(1, 2, Purpose.RESET, 3, 101, 1901)
        self.assertTrue(action_allowed(self.employee, pending, action, Purpose.RESET, now=1900))
        self.assertFalse(action_allowed(self.employee, pending, action, Purpose.RESET, now=1901))
        self.assertFalse(login_allowed(self.employee, pending))

    def test_complete_reset_once_and_repeat_reset_invalidates_old_action(self):
        pending = begin_reset(self.credential)
        action = PasswordAction(1, 2, Purpose.RESET, 3, 101, 1901)
        ready, used = complete_reset(self.employee, pending, action, new_password_hash="opaque-new", now=102)
        self.assertTrue(login_allowed(self.employee, ready))
        self.assertEqual(ready.version, 3)
        for credential, candidate in ((ready, used), (pending, used),
                                       (begin_reset(pending), action),
                                       (pending, replace(action, revoked_at=102)),
                                       (pending, replace(action, credential_id=2))):
            with self.assertRaises(PermissionError):
                complete_reset(self.employee, credential, candidate, new_password_hash="opaque-new", now=103)
        self.assertNotIn("opaque", repr(ready))

    def test_reset_cannot_reenable_inactive_account_or_change_employee(self):
        pending = begin_reset(replace(self.credential, active=False))
        action = PasswordAction(1, 2, Purpose.RESET, 3, 101, 1901)
        for emp, cred in ((self.employee, pending),
                          (replace(self.employee, active=False), replace(pending, active=True))):
            with self.assertRaises(PermissionError):
                complete_reset(emp, cred, action, new_password_hash="opaque-new", now=102)
        self.assertEqual(self.employee, Employee(1, Role.MANAGER, True))

    def test_invitation_is_distinct_and_requires_explicit_lifetime(self):
        invited = Credential(1, 1, True, CredentialState.INVITED, 1)
        action = PasswordAction(1, 1, Purpose.INVITATION, 3, 100, 500)
        self.assertTrue(action_allowed(self.employee, invited, action, Purpose.INVITATION, now=101))
        self.assertFalse(action_allowed(self.employee, invited, action, Purpose.RESET, now=101))
        self.assertFalse(action_allowed(self.employee, invited, action, Purpose.INVITATION, now=99))

    def test_closed_states_types_and_immutability(self):
        for factory in (lambda: Employee(True, Role.MANAGER, True),
                        lambda: Employee(1, "supervisor", True),
                        lambda: Credential(1, 1, True, CredentialState.RESET_PENDING, 1, "opaque"),
                        lambda: replace(self.session, absolute_expires_at=101),
                        lambda: PasswordAction(1, 1, Purpose.RESET, 3, 100, 101)):
            with self.assertRaises(ValueError):
                factory()
        with self.assertRaises(FrozenInstanceError):
            self.employee.role = Role.SUPERVISOR
