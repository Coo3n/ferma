"""Трансляция экранов: один захватчик кадров на устройство, много зрителей."""
from .frames import BOUNDARY, FrameSource, drop, mjpeg, snapshot, source, thumbnail

__all__ = ["BOUNDARY", "FrameSource", "source", "drop", "mjpeg", "snapshot", "thumbnail"]
