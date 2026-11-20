"""RGB Phone 2.1 (simple mode) - remote for your PC's RGB lights (OpenRGB).

Phone --TLS + remembered certificate + short shared password--> RGB Gateway on PC
--> OpenRGB (127.0.0.1 only).  Home-network only; no PIN / app lock in this version.
"""
import os
import threading
import colorsys
from math import atan2, cos, sin, pi, hypot

from kivy.app import App
from kivy.clock import Clock
from kivy.graphics import Color, Quad, Ellipse, Line
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

import security as sec
import tunnel

# Pure LED colours (washed-out mixes like 225,29,29 look pink on LEDs)
PRESETS = [
    ("Blue", (0, 0, 255)), ("Red", (255, 0, 0)), ("Green", (0, 255, 0)),
    ("Purple", (150, 0, 255)), ("Cyan", (0, 255, 255)), ("Orange", (255, 60, 0)),
    ("Pink", (255, 0, 110)), ("White", (255, 255, 255)),
]
RED = (1, 0.45, 0.45, 1)
GREY = (0.2, 0.2, 0.25, 1)


class Lights:
    """Talks to OpenRGB, but only through the authenticated TLS tunnel (never directly)."""

    def __init__(self, get_cfg, save_cfg=None):
        self.get_cfg = get_cfg
        self.save_cfg = save_cfg
        self.client = None
        self.rgb = (0, 0, 255)
        self.bright = 100
        self.lock = threading.Lock()
        self.direct = False

    def close(self):
        with self.lock:
            self.client = None
            self.direct = False

    def connect(self):
        from openrgb import OpenRGBClient
        cfg = self.get_cfg()
        pair = cfg["pair"]
        port = tunnel.open_tunnel(cfg["host"], int(cfg.get("port", sec.DEFAULT_GATEWAY_PORT)), pair)
        # Simple mode: remember the PC's certificate after the FIRST accepted login
        seen = pair.pop("seen_fp", None)
        if seen and not pair.get("fp") and self.save_cfg:
            pair["fp"] = seen
            self.save_cfg()
        self.client = OpenRGBClient("127.0.0.1", port, name="RGB Phone")
        self.direct = False
        self._ensure_direct()
        return len(self.client.devices)

    def _ensure_direct(self):
        # After a PC restart lights fall back to a hardware effect; force Direct/Static
        if self.direct:
            return
        for d in self.client.devices:
            for name in ("direct", "static"):
                try:
                    d.set_mode(name)
                    break
                except Exception:
                    continue
        self.direct = True

    def _ensure(self):
        if self.client is None:
            self.connect()
        self._ensure_direct()

    def _try(self, action):
        """Run action(). If an ALREADY-OPEN connection has gone stale (idle timeout, Wi-Fi blip),
        reconnect once and repeat, so the first button press is not lost.
        A first-time connect failure (PC off, wrong code) is NOT retried."""
        with self.lock:
            had_conn = self.client is not None
            try:
                self._ensure()
                return action()
            except Exception:
                self.client = None
                self.direct = False
                if not had_conn:
                    raise
            try:
                self._ensure()
                return action()
            except Exception:
                self.client = None
                self.direct = False
                raise

    def _color(self, r, g, b):
        from openrgb.utils import RGBColor
        self._try(lambda: self.client.set_color(RGBColor(r, g, b)))

    def apply(self):
        f = self.bright / 100.0
        r, g, b = self.rgb
        self._color(int(r * f), int(g * f), int(b * f))

    def set_rgb(self, rgb):
        self.rgb = tuple(int(v) for v in rgb)
        self.apply()

    def set_brightness(self, v):
        self.bright = max(0, min(100, int(v)))
        self.apply()

    def off(self):
        self._color(0, 0, 0)

    def rainbow(self):
        def go():
            ok = False
            for d in self.client.devices:
                for m in d.modes:
                    if "rainbow" in m.name.lower() or "spectrum" in m.name.lower():
                        try:
                            d.set_mode(m.name)
                            ok = True
                        except Exception:
                            pass
                        break
            self.direct = False
            return ok
        return self._try(go)


def lbl(text, **kw):
    return Label(text=text, **kw)


def field(**kw):
    kw.setdefault("multiline", False)
    kw.setdefault("font_size", "20sp")
    kw.setdefault("size_hint_y", None)
    kw.setdefault("height", 56)
    return TextInput(**kw)


def pin_field(hint):
    return field(hint_text=hint, password=True, input_filter="int")


def button(text, cb, **kw):
    kw.setdefault("size_hint_y", None)
    kw.setdefault("height", 56)
    kw.setdefault("font_size", "18sp")
    b = Button(text=text, **kw)
    b.bind(on_release=lambda *_: cb())
    return b


# --------------------------------------------------------------- UI ---
class HueRing(Widget):
    """Smooth colour ring: touch or drag anywhere around it, colour follows your finger."""

    def __init__(self, on_change, **kw):
        super().__init__(**kw)
        self.on_change = on_change
        self.hue = 0.62
        self.bind(pos=self._redraw, size=self._redraw)

    def _geom(self):
        R = min(self.width, self.height) / 2 * 0.96
        return self.center_x, self.center_y, R, R * 0.58

    def _redraw(self, *_):
        self.canvas.clear()
        cx, cy, R, r = self._geom()
        n = 180
        with self.canvas:
            for i in range(n):
                a0 = 2 * pi * i / n
                a1 = 2 * pi * (i + 1) / n + 0.012
                Color(*colorsys.hsv_to_rgb(i / n, 1, 1))
                Quad(points=[cx + R * cos(a0), cy + R * sin(a0),
                             cx + R * cos(a1), cy + R * sin(a1),
                             cx + r * cos(a1), cy + r * sin(a1),
                             cx + r * cos(a0), cy + r * sin(a0)])
        self._marker()

    def _marker(self):
        cx, cy, R, r = self._geom()
        self.canvas.after.clear()
        a = 2 * pi * self.hue
        mr = (R + r) / 2
        mx, my = cx + mr * cos(a), cy + mr * sin(a)
        rad = max((R - r) * 0.42, 6)
        with self.canvas.after:
            Color(*colorsys.hsv_to_rgb(self.hue, 1, 1))
            Ellipse(pos=(cx - r * 0.78, cy - r * 0.78), size=(r * 1.56, r * 1.56))
            Color(0, 0, 0, 0.7)
            Line(circle=(mx, my, rad + 2), width=2)
            Color(1, 1, 1, 1)
            Line(circle=(mx, my, rad), width=2.5)

    def _from_touch(self, touch):
        cx, cy, R, r = self._geom()
        dx, dy = touch.x - cx, touch.y - cy
        if dx == 0 and dy == 0:
            return
        self.hue = (atan2(dy, dx) % (2 * pi)) / (2 * pi)
        self._marker()
        self.on_change([int(c * 255) for c in colorsys.hsv_to_rgb(self.hue, 1, 1)])

    def on_touch_down(self, touch):
        cx, cy, R, r = self._geom()
        d = hypot(touch.x - cx, touch.y - cy)
        if r * 0.75 <= d <= R * 1.15:
            touch.grab(self)
            self._from_touch(touch)
            return True
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if touch.grab_current is self:
            self._from_touch(touch)
            return True
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            touch.ungrab(self)
            return True
        return super().on_touch_up(touch)


class RGBPhoneApp(App):
    title = "RGB Phone"

    def build(self):
        from kivy.core.window import Window
        Window.clearcolor = (0.06, 0.06, 0.1, 1)
        self.cfg_path = os.path.join(self.user_data_dir, "config.json")
        self.cfg = sec.migrate(sec.load_cfg(self.cfg_path))
        self.lights = Lights(lambda: self.cfg, lambda: sec.save_cfg(self.cfg_path, self.cfg))
        self._pending = None
        self._bright = 100
        self._color_ev = False
        self._bright_ev = False
        self._tick = None
        self.unlocked = False
        self.status = None
        self.root_box = BoxLayout(orientation="vertical", padding=16, spacing=10)
        if sec.needs_pairing(self.cfg):
            self.setup_screen()
        else:
            self.main_screen()
        return self.root_box

    # ----- helpers
    def page(self, title):
        """Fresh scrollable column; returns the inner layout."""
        self.stop_tick()
        self.status = None
        self.root_box.clear_widgets()
        sv = ScrollView(do_scroll_x=False)
        col = BoxLayout(orientation="vertical", spacing=10, size_hint_y=None, padding=(0, 0, 0, 20))
        col.bind(minimum_height=col.setter("height"))
        sv.add_widget(col)
        self.root_box.add_widget(sv)
        col.add_widget(lbl(title, font_size="24sp", size_hint_y=None, height=60))
        return col

    def note(self, col, text, h=None, **kw):
        l = lbl(text, size_hint_y=None, halign="left", valign="top", **kw)
        l.bind(width=lambda w, v: setattr(w, "text_size", (v, None)))
        l.bind(texture_size=lambda w, s: setattr(w, "height", max(s[1], 28) if h is None else h))
        col.add_widget(l)
        return l

    def msg_label(self, col):
        self.msg = self.note(col, "", color=RED)
        return self.msg

    def stop_tick(self):
        if self._tick is not None:
            self._tick.cancel()
            self._tick = None

    # ----- setup / settings (simple mode: PC IP + one short shared password)
    def setup_screen(self, first=True):
        col = self.page("RGB Phone setup" if first else "PC / password")
        self.note(col, "PC par 'set_password.bat' se jo password chuna tha, wo yahan daalo. "
                       "Dost bhi apne PC ka IP aur apna password daalenge.")
        self.ip_in = field(text=self.cfg.get("host", ""), hint_text="PC IP (jaise 192.168.1.8)",
                           keyboard_suggestions=False)
        col.add_widget(self.ip_in)
        self.port_in = field(text=str(self.cfg.get("port", sec.DEFAULT_GATEWAY_PORT)),
                             hint_text="Port", input_filter="int")
        col.add_widget(self.port_in)
        self.pw_in = field(hint_text="Password", keyboard_suggestions=False)
        col.add_widget(self.pw_in)
        self.msg_label(col)
        col.add_widget(button("Save", self.save_setup))
        if not first:
            col.add_widget(button("Wapas", self.main_screen, background_color=GREY))

    def read_connection(self):
        """Validate IP/port/password. Returns (error, host, port, pair).

        Also accepts a long 'RGB1....' pairing code (strict mode) in the password box."""
        err = sec.validate_host(self.ip_in.text)
        if err:
            return err, None, None, None
        host = self.ip_in.text.strip()
        port = sec.validate_port(self.port_in.text)
        if port is None:
            return "Port 1024-65535 ke beech ho (aam taur par 6743)", None, None, None
        text = self.pw_in.text.strip()
        pair = sec.parse_pairing_code(text) if text.startswith("RGB1.") else None
        if pair is None:
            err = sec.validate_password(text)
            if err:
                return err, None, None, None
            pair = sec.make_simple_pair(text)
        return None, host, port, pair

    def save_setup(self):
        err, host, port, pair = self.read_connection()
        if err:
            self.msg.text = err
            return
        self.cfg.update({"host": host, "port": port, "pair": pair})
        sec.save_cfg(self.cfg_path, self.cfg)
        self.lights.close()
        self.main_screen()

    # ----- main screen (all lighting controls)
    def main_screen(self):
        self.unlocked = True
        self.stop_tick()
        r = self.root_box
        r.clear_widgets()
        top = BoxLayout(size_hint_y=0.07, spacing=8)
        self.status = lbl("Connecting...", halign="left")
        self.status.bind(size=lambda w, s: setattr(w, "text_size", s))
        top.add_widget(self.status)
        top.add_widget(button("Settings", lambda: self.setup_screen(first=False),
                              size_hint_x=0.3, size_hint_y=1))
        r.add_widget(top)

        self.ring = HueRing(self.on_ring, size_hint_y=0.45)
        r.add_widget(self.ring)

        r.add_widget(lbl("Brightness", size_hint_y=0.04))
        sl = Slider(min=0, max=100, value=100, size_hint_y=0.07)
        sl.bind(value=self.on_bright)
        r.add_widget(sl)

        grid = GridLayout(cols=4, spacing=8, size_hint_y=0.18)
        for name, rgb in PRESETS:
            btn = Button(text=name, background_normal="", font_size="14sp",
                         background_color=(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, 1),
                         color=(0, 0, 0, 1) if name in ("White", "Cyan", "Green") else (1, 1, 1, 1))
            btn.bind(on_release=lambda _b, c=rgb: self.run_bg(self.lights.set_rgb, c))
            grid.add_widget(btn)
        r.add_widget(grid)

        row = BoxLayout(size_hint_y=0.12, spacing=10)
        rb = Button(text="Rainbow", font_size="20sp", background_color=(0.3, 0.2, 0.55, 1))
        rb.bind(on_release=lambda *_: self.run_bg(self.lights.rainbow))
        ob = Button(text="Off", font_size="20sp", background_color=(0.2, 0.2, 0.2, 1))
        ob.bind(on_release=lambda *_: self.run_bg(self.lights.off))
        row.add_widget(rb)
        row.add_widget(ob)
        r.add_widget(row)

        self.run_bg(self.lights.connect, note="Connected")

    # ----- app goes to background / comes back (no lock in simple mode)
    def on_pause(self):
        return True

    def on_resume(self):
        pass

    def on_stop(self):
        self.lights.close()

    # ----- actions (network calls run off the UI thread)
    def set_status(self, text):
        def upd(_dt):
            if self.status is not None:
                self.status.text = text
        Clock.schedule_once(upd, 0)

    def run_bg(self, fn, *args, note=None):
        def work():
            try:
                res = fn(*args)
                if note:
                    self.set_status("%s (%s devices)" % (note, res) if isinstance(res, int) else note)
                else:
                    self.set_status("OK")
            except Exception as e:
                self.set_status("Error: %s" % str(e)[:70])
        threading.Thread(target=work, daemon=True).start()

    # Throttled: sends the newest colour about every 70 ms while you drag
    def on_ring(self, rgb):
        self._pending = rgb
        if not self._color_ev:
            self._color_ev = True
            Clock.schedule_once(self._flush_color, 0.07)

    def _flush_color(self, _dt):
        self._color_ev = False
        self.run_bg(self.lights.set_rgb, self._pending)

    def on_bright(self, _s, v):
        self._bright = v
        if not self._bright_ev:
            self._bright_ev = True
            Clock.schedule_once(self._flush_bright, 0.07)

    def _flush_bright(self, _dt):
        self._bright_ev = False
        self.run_bg(self.lights.set_brightness, self._bright)


if __name__ == "__main__":
    RGBPhoneApp().run()
