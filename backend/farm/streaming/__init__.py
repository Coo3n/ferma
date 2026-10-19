"""Трансляция экранов: один захватчик кадров на устройство, много зрителей."""
from .frames import BOUNDARY, FrameSource, drop, mjpeg, note_action, snapshot, source, thumbnail

__all__ = ["BOUNDARY", "FrameSource", "source", "drop", "mjpeg", "note_action", "snapshot", "thumbnail"]
