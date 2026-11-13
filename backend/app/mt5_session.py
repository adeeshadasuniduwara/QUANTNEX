"""Shared synchronization for the process-wide MetaTrader 5 terminal API.

The official MetaTrader5 Python package talks to a single terminal connection.
Market-data reads and the optional Prop Challenge DEMO guardian must not
initialize, shut down, or issue terminal calls concurrently.
"""
from threading import RLock

MT5_LOCK = RLock()
