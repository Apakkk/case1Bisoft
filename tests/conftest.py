"""Every test logs in with a fixed test account, never the real one from .env.

Set at import time because `app.main` builds its module-level app (and so reads the settings) when it is first
imported, before any fixture runs. Environment variables outrank .env in pydantic-settings.
"""

import os

from tests.clients import TEST_EMAIL, TEST_PASSWORD

os.environ["ADMIN_EMAIL"] = TEST_EMAIL
os.environ["ADMIN_PASSWORD"] = TEST_PASSWORD
