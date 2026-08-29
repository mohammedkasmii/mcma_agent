"""
Root conftest — INC-01 defense-in-depth guard installation.

The egress guard plugin is loaded before collection via `-p
testsupport.egress_guard` in pyproject.toml addopts; importing and installing
it here as well guarantees the guard is active even if the addopts path is
bypassed. install() is idempotent, so the double path never double-wraps.
"""

from testsupport import egress_guard

egress_guard.install()
