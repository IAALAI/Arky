#!/usr/bin/python3
"""Display and control the existing Waydroid session without a video encoder."""

import subprocess
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib  # noqa: E402

SERIAL = "192.168.240.112:5555"


class View(Gtk.Window):
    def __init__(self):
        super().__init__(title="Arky - Waydroid 实时画面")
        self.set_default_size(1100, 655)
        self.frame = None
        self.touch = None
        self.stopped = threading.Event()
        self.frames = 0
        self.rendered_size = None
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(box)
        self.canvas = Gtk.EventBox()
        self.picture = Gtk.Image()
        self.canvas.add(self.picture)
        self.canvas.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
        )
        self.canvas.connect("size-allocate", lambda *args: self.refresh())
        self.canvas.connect("button-press-event", self.press)
        self.canvas.connect("button-release-event", self.release)
        box.pack_start(self.canvas, True, True, 0)
        self.status = Gtk.Label(label="连接实时画面…")
        box.pack_start(self.status, False, False, 5)
        self.connect("destroy", self.close)
        self.connect(
            "map-event", lambda *args: print("Desktop window mapped", flush=True)
        )
        self.show_all()
        threading.Thread(target=self.capture, daemon=True).start()

    def geometry(self):
        width, height = (
            self.canvas.get_allocated_width(),
            self.canvas.get_allocated_height(),
        )
        scale = min(width / self.frame.get_width(), height / self.frame.get_height())
        return (
            scale,
            (width - self.frame.get_width() * scale) / 2,
            (height - self.frame.get_height() * scale) / 2,
        )

    def refresh(self):
        if self.frame:
            scale, x, y = self.geometry()
            size = (
                max(1, int(self.frame.get_width() * scale)),
                max(1, int(self.frame.get_height() * scale)),
            )
            if size != self.rendered_size:
                self.rendered_size = size
                self.picture.set_from_pixbuf(
                    self.frame.scale_simple(*size, GdkPixbuf.InterpType.BILINEAR)
                )

    def point(self, event):
        if self.frame is None:
            return None
        scale, x, y = self.geometry()
        px, py = int((event.x - x) / scale), int((event.y - y) / scale)
        if 0 <= px < self.frame.get_width() and 0 <= py < self.frame.get_height():
            return px, py

    def press(self, widget, event):
        if event.button == 1:
            point = self.point(event)
            self.touch = (point, time.monotonic()) if point else None

    def release(self, widget, event):
        point = self.point(event)
        if event.button != 1 or not point or not self.touch:
            self.touch = None
            return
        start, stamp = self.touch
        self.touch = None
        duration = min(1000, max(150, int((time.monotonic() - stamp) * 1000)))

        def inject():
            try:
                subprocess.run(
                    [
                        "adb",
                        "-s",
                        SERIAL,
                        "shell",
                        "input",
                        "swipe",
                        *map(str, (*start, *point, duration)),
                    ],
                    check=True,
                    capture_output=True,
                    timeout=5,
                )
            except (subprocess.SubprocessError, OSError) as exc:
                GLib.idle_add(self.status.set_text, "输入失败：" + str(exc))

        threading.Thread(target=inject, daemon=True).start()

    def capture(self):
        while not self.stopped.is_set():
            try:
                result = subprocess.run(
                    ["adb", "-s", SERIAL, "exec-out", "screencap", "-p"],
                    check=True,
                    capture_output=True,
                    timeout=5,
                )
                loader = GdkPixbuf.PixbufLoader.new_with_type("png")
                loader.write(result.stdout)
                loader.close()
                frame = loader.get_pixbuf()
                GLib.idle_add(
                    self.update,
                    frame,
                    datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%H:%M:%S"),
                )
            except Exception as exc:
                GLib.idle_add(
                    self.status.set_text,
                    "实时画面连接中断（保留的是旧画面）：" + str(exc),
                )
            self.stopped.wait(0.5)

    def update(self, frame, stamp):
        if self.stopped.is_set():
            return False
        self.frame = frame
        self.frames += 1
        self.rendered_size = None
        self.status.set_text(
            "低帧率实时画面 · 更新于 "
            + stamp
            + " · 鼠标可点击/拖动 · 关闭窗口不停止游戏"
        )
        self.refresh()
        if self.frames in (1, 10):
            print(
                "Live frame",
                self.frames,
                frame.get_width(),
                frame.get_height(),
                flush=True,
            )
        return False

    def close(self, *args):
        self.stopped.set()
        Gtk.main_quit()


View()
Gtk.main()
