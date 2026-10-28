"""Workspace has no CRM export authority, including accidentally started workers."""

import os


def workspace_runtime():
    return os.environ.get("WORKSPACE_RUNTIME") == "1"


def require_legacy_export():
    if workspace_runtime():
        raise PermissionError("CRM export is disabled in workspace runtime")
