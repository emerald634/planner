"""Explicit bridge capability. Deliberately excluded from legacy release profiles.

Only the reviewed foundation DDL is supported. No web login or auth mutations.
"""
from .web_auth.schema import MANIFEST_CHECKSUM
from .web_auth.validation import validate_schema

BRIDGE_VERSION = "schema5-compat-v1"
SUPPORTED_SCHEMAS = (4, 5)


def validate_schema5(db):
    validate_schema(db, 5)
