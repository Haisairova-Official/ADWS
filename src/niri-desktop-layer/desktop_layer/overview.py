"""Observe Niri overview state through its event-only IPC connection.

There is no subprocess, compositor action, or periodic state polling.  Socket
readiness and bounded reconnect attempts run on the default GLib main context,
which is also where the supplied callback is invoked.
"""

from __future__ import annotations
from .i18n import tr as _tr

import errno
import json
import logging
import os
import socket
from typing import Callable

from gi.repository import GLib


LOG = logging.getLogger("desktop-layer.overview")
_REQUEST = b'"EventStream"\n'
_MAX_LINE_BYTES = 2 * 1024 * 1024
_READ_SIZE = 64 * 1024
_READ_BUDGET = 256 * 1024
_RETRY_DELAYS_MS = (500, 1000, 2000, 4000, 8000, 16000)
_READ_CONDITIONS = GLib.IOCondition.IN | GLib.IOCondition.HUP | GLib.IOCondition.ERR | GLib.IOCondition.NVAL


class OverviewWatcher:
    """Call ``callback(is_open)`` for Niri's initial overview state and changes.

    ``start()`` and ``close()`` are idempotent and should be called on the GTK
    thread.  A missing NIRI_SOCKET disables observation quietly.  A failed or
    lost connection receives at most six exponential-backoff retries; another
    explicit close/start cycle can restart an exhausted watcher.  A successful
    overview event resets the retry allowance.
    """

    def __init__(self, callback: Callable[[bool], None]):
        self.callback = callback
        self._socket = None
        self._watch = 0
        self._retry_source = 0
        self._retry_index = 0
        self._closed = True
        self._connecting = False
        self._pending = b""
        self._buffer = bytearray()
        self._last_state = None
        self._path = None

    def start(self):
        if not self._closed:
            return self
        self._closed = False
        self._retry_index = 0
        self._last_state = None
        self._path = os.environ.get("NIRI_SOCKET")
        if self._path:
            self._connect()
        else:
            LOG.debug(_tr('NIRI_SOCKET 未设置，概览状态监听已停用'))
        return self

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._retry_source:
            GLib.source_remove(self._retry_source)
            self._retry_source = 0
        self._drop_socket()

    def _connect(self):
        if self._closed:
            return
        try:
            self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._socket.setblocking(False)
            result = self._socket.connect_ex(self._path)
            if result in (0, errno.EISCONN):
                self._connecting = False
            elif result in (errno.EINPROGRESS, errno.EALREADY, errno.EWOULDBLOCK):
                self._connecting = True
            else:
                raise OSError(result, os.strerror(result))
            self._pending = _REQUEST
            if not self._connecting:
                self._flush_request()
            self._add_watch()
        except (OSError, ValueError) as exc:
            self._disconnected(str(exc))

    def _add_watch(self):
        conditions = _READ_CONDITIONS
        if self._connecting or self._pending:
            conditions |= GLib.IOCondition.OUT
        self._watch = GLib.io_add_watch(
            self._socket.fileno(), GLib.PRIORITY_DEFAULT, conditions, self._io_ready
        )

    def _flush_request(self):
        while self._pending:
            try:
                sent = self._socket.send(self._pending)
            except BlockingIOError:
                return
            if not sent:
                raise OSError(_tr('Niri IPC 请求发送失败'))
            self._pending = self._pending[sent:]

    def _io_ready(self, _channel, condition):
        if self._closed or self._socket is None:
            self._watch = 0
            return False
        had_write_interest = self._connecting or bool(self._pending)
        try:
            if self._connecting:
                result = self._socket.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                if result:
                    raise OSError(result, os.strerror(result))
                self._connecting = False
            if self._pending:
                self._flush_request()
            if condition & GLib.IOCondition.IN:
                remaining = _READ_BUDGET
                while remaining > 0 and not self._closed:
                    try:
                        chunk = self._socket.recv(min(_READ_SIZE, remaining))
                    except BlockingIOError:
                        break
                    if not chunk:
                        raise OSError(_tr('Niri IPC 连接已关闭'))
                    remaining -= len(chunk)
                    self._feed(chunk)
            if self._closed:
                return False
            if condition & (GLib.IOCondition.HUP | GLib.IOCondition.ERR | GLib.IOCondition.NVAL):
                raise OSError(_tr('Niri IPC 连接已断开'))
        except (OSError, ValueError) as exc:
            self._disconnected(str(exc), from_watch=True)
            return False
        if had_write_interest and not (self._connecting or self._pending):
            # The running source removes itself on return; never leave an OUT
            # watch on a connected socket, which would wake the loop constantly.
            self._watch = 0
            self._add_watch()
            return False
        return True

    def _feed(self, chunk):
        self._buffer.extend(chunk)
        while not self._closed:
            boundary = self._buffer.find(b"\n")
            if boundary < 0:
                if len(self._buffer) > _MAX_LINE_BYTES:
                    raise ValueError(_tr('Niri IPC 消息超过大小限制'))
                return
            if boundary > _MAX_LINE_BYTES:
                raise ValueError(_tr('Niri IPC 消息超过大小限制'))
            raw = bytes(self._buffer[:boundary])
            del self._buffer[:boundary + 1]
            try:
                event = json.loads(raw)
            except (ValueError, UnicodeError, RecursionError):
                LOG.debug(_tr('忽略无法解析的 Niri IPC 消息'))
                continue
            if not isinstance(event, dict):
                continue
            if "Err" in event:
                raise ValueError(_tr('Niri 拒绝 EventStream 请求'))
            state = event.get("OverviewOpenedOrClosed")
            if isinstance(state, dict) and type(state.get("is_open")) is bool:
                self._retry_index = 0
                self._set_state(state["is_open"])

    def _set_state(self, state):
        if state == self._last_state:
            return
        self._last_state = state
        try:
            self.callback(state)
        except Exception:
            LOG.exception(_tr('概览状态回调失败'))

    def _drop_socket(self, from_watch=False):
        if self._watch:
            if not from_watch:
                GLib.source_remove(self._watch)
            self._watch = 0
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None
        self._buffer.clear()
        self._pending = b""
        self._connecting = False

    def _disconnected(self, reason, from_watch=False):
        self._drop_socket(from_watch=from_watch)
        if self._last_state is True and not self._closed:
            self._set_state(False)
        if self._closed or self._retry_source:
            return
        if self._retry_index >= len(_RETRY_DELAYS_MS):
            LOG.warning(_tr('概览监听无法连接 Niri，重试次数已用尽：%s'), reason)
            return
        delay = _RETRY_DELAYS_MS[self._retry_index]
        self._retry_index += 1
        LOG.debug(_tr('概览监听连接中断，%d 毫秒后重试：%s'), delay, reason)
        self._retry_source = GLib.timeout_add(delay, self._retry)

    def _retry(self):
        self._retry_source = 0
        self._connect()
        return False
