from __future__ import annotations

import django
from django.conf import settings


def pytest_configure():
    if not settings.configured:
        settings.configure(
            EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
            INSTALLED_APPS=[],
            SECRET_KEY="test",
        )
    django.setup()
    # Ensure mail.outbox exists for pytest-django autouse fixture.
    from django.core.mail.backends import locmem  # noqa: F401
