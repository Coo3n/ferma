"""Трансляция экранов: один захватчик кадров на устройство, много зрителей."""
from .frames import BOUNDARY, FrameSource, drop, is_live, mjpeg, note_action, snapshot, source, thumbnail

__all__ = ["BOUNDARY", "FrameSource", "source", "drop", "mjpeg", "is_live", "note_action", "snapshot", "thumbnail"]
