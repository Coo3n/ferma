"""Трансляция экранов: один захватчик кадров на устройство, много зрителей."""
from .frames import BOUNDARY, FrameSource, drop, is_live, mjpeg, note_action, screen_info, screen_refresh, snapshot, source, thumbnail

__all__ = ["BOUNDARY", "FrameSource", "source", "drop", "mjpeg", "is_live", "note_action", "screen_info", "screen_refresh", "snapshot", "thumbnail"]
