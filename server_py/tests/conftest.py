import os

# Settings needs a database URL to exist; no test opens a database connection.
os.environ.setdefault("DATABASE_URL", "postgresql://user:password@localhost/test")

import pytest  # noqa: E402

from app.modules.chat_bot import autocare_client  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_catalog_cache():
    autocare_client.reset_catalog_cache()
    yield
    autocare_client.reset_catalog_cache()
