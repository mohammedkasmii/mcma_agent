"""
testsupport — explicit, importable test-support package (INC-01).

Holds the pre-collection egress guard / pytest plugin. This is a real
package (with __init__.py) rather than an implicit namespace package so the
plugin import path is unambiguous and cannot collide with an installed
distribution. Nothing in here is production code.
"""
