"""Bounded test-only access to Qt's unbound accessibility update handler."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass

from PySide6.QtGui import (
    QAccessible,
    QAccessibleAnnouncementEvent,
    QAccessibleEvent,
)
import shiboken6


@dataclass(frozen=True, slots=True)
class RecordedAnnouncement:
    message: str
    politeness: QAccessible.AnnouncementPoliteness


class AnnouncementRecorder:
    """Install and restore Qt's synchronous update hook for one test scope."""

    _SYMBOL = "_ZN11QAccessible20installUpdateHandlerEPFvP16QAccessibleEventE"

    def __init__(self) -> None:
        self.announcements: list[RecordedAnnouncement] = []
        self._library = ctypes.CDLL("libQt6Gui.so.6")
        self._install = getattr(self._library, self._SYMBOL)
        self._install.argtypes = [ctypes.c_void_p]
        self._install.restype = ctypes.c_void_p
        self._callback_type = ctypes.CFUNCTYPE(None, ctypes.c_void_p)
        self._callback: object | None = None
        self._previous: int | None = None

    def __enter__(self) -> AnnouncementRecorder:
        def record(event_pointer: int) -> None:
            event = shiboken6.wrapInstance(event_pointer, QAccessibleEvent)
            if event.type() != QAccessible.Event.Announcement:
                return
            shiboken6.invalidate(event)
            announcement = shiboken6.wrapInstance(
                event_pointer,
                QAccessibleAnnouncementEvent,
            )
            try:
                self.announcements.append(
                    RecordedAnnouncement(
                        announcement.message(),
                        announcement.politeness(),
                    )
                )
            finally:
                shiboken6.invalidate(announcement)

        self._callback = self._callback_type(record)
        callback_pointer = ctypes.cast(self._callback, ctypes.c_void_p)
        self._previous = self._install(callback_pointer)
        return self

    def __exit__(self, *_: object) -> None:
        self._install(ctypes.c_void_p(self._previous or 0))
        self._callback = None
