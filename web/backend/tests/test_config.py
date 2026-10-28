import logging

from app.core.config import Settings, warn_if_insecure_defaults


def test_warns_on_default_secrets(caplog):
    config = Settings(
        jwt_secret="local-development-secret-change-me-32-bytes",
        first_admin_password="",  # Bootstrap now has no built-in password.
    )
    with caplog.at_level(logging.WARNING):
        warn_if_insecure_defaults(config)
    assert "JWT_SECRET" in caplog.text
    assert "FIRST_ADMIN_PASSWORD" in caplog.text


def test_no_warning_for_custom_secrets(caplog):
    config = Settings(
        jwt_secret="a-real-random-secret-value-1234567890",
        first_admin_password="Sup3rSecurePass!42",
    )
    with caplog.at_level(logging.WARNING):
        warn_if_insecure_defaults(config)
    assert caplog.text == ""
