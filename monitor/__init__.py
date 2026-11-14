"""EU Outside-In Tracking Monitor.

Deterministic core: fetch pages and Tealium files, collect evidence, run checks,
rate markets. Claude (or any other tool) only reads the JSON results it produces.
"""

__version__ = "1.0.0"
SCHEMA_VERSION = 1
USER_AGENT_SUFFIX = "SageTrackingMonitor/1.0"
