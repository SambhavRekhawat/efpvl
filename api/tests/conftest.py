"""Test configuration.

Rate limiting is disabled for the suite: every test shares one client IP and
would otherwise exhaust the public budget. Limiter behaviour has its own
dedicated test that enables it explicitly.
"""

import os

os.environ.setdefault("EFPVL_RATE_BUDGET", "0")
