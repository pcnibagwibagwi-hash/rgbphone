"""RGB Phone 2.0 - secure remote for your PC's RGB lights (OpenRGB).

Phone --TLS + pinned certificate + per-device secret--> RGB Gateway on PC --> OpenRGB (127.0.0.1 only).
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

    def __init__(self, get_cfg):
        self.get_cfg = get_cfg
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
        port = tunnel.open_tunnel(cfg["host"], int(cfg.get("port", sec.DEFAULT_GATEWAY_PORT)),
                                  cfg["pair"])
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
        self.lights = Lights(lambda: self.cfg)
        self._pending = None
        self._bright = 100
        self._color_ev = False
        self._bright_ev = False
        self._tick = None
        self.unlocked = False
        self.status = None
        self.root_box = BoxLayout(orientation="vertical", padding=16, spacing=10)
        if not sec.is_configured(self.cfg):
            self.setup_screen()
        else:
            self.pin_screen()
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

    def watch_lock(self):
        """While locked, show a live countdown."""
        self.stop_tick()

        def tick(_dt):
            left = sec.lock_remaining(self.cfg)
            if left:
                self.msg.text = "Bahut galat try. %d second ruko" % left
            else:
                self.msg.text = ""
                self.stop_tick()
        if sec.lock_remaining(self.cfg):
            tick(0)
            self._tick = Clock.schedule_interval(tick, 1)

    # ----- first-time setup
    def setup_screen(self):
        col = self.page("RGB Phone setup")
        self.note(col, "1) PC par gateway chalu karo aur 'add-device' se pairing code lo (README dekho).")
        self.ip_in = field(text=self.cfg.get("host", ""), hint_text="PC IP (jaise 192.168.1.8)")
        col.add_widget(self.ip_in)
        self.port_in = field(text=str(self.cfg.get("port", sec.DEFAULT_GATEWAY_PORT)),
                             hint_text="Port", input_filter="int")
        col.add_widget(self.port_in)
        self.pair_in = field(hint_text="Pairing code (RGB1....)")
        col.add_widget(self.pair_in)
        self.note(col, "2) Apna PIN banao (6 se 12 digit, 123456 jaisa easy nahi):")
        self.pin1 = pin_field("PIN")
        self.pin2 = pin_field("PIN dobara")
        col.add_widget(self.pin1)
        col.add_widget(self.pin2)
        self.msg_label(col)
        col.add_widget(button("Save", self.save_setup))

    def read_connection(self):
        """Validate host/port/pairing fields. Returns (error, host, port, pair)."""
        err = sec.validate_host(self.ip_in.text)
        host = self.ip_in.text.strip()
        port = sec.validate_port(self.port_in.text)
        pair = sec.parse_pairing_code(self.pair_in.text)
        if err:
            return err, None, None, None
        if port is None:
            return "Port 1024-65535 ke beech ho (aam taur par 6743)", None, None, None
        if pair is None:
            return "Pairing code galat hai. Poora code copy karo (RGB1. se shuru)", None, None, None
        return None, host, port, pair

    def save_setup(self):
        err, host, port, pair = self.read_connection()
        if not err and self.pin1.text != self.pin2.text:
            err = "Dono PIN same nahi hain"
        if not err:
            err = sec.validate_pin(self.pin1.text)
        if err:
            self.msg.text = err
            return
        self.cfg.update({"host": host, "port": port, "pair": pair})
        code = sec.create_pin(self.cfg, self.cfg_path, self.pin1.text)
        self.recovery_screen(code, then=self.main_screen)

    def recovery_screen(self, code, then):
        col = self.page("Recovery code")
        self.note(col, "Ye code ABHI kahin likh lo (kagaz par). PIN bhool gaye to sirf yahi kaam aayega. "
                       "Ye dobara nahi dikhega.")
        l = lbl(sec.format_recovery(code), font_size="26sp", size_hint_y=None, height=80)
        col.add_widget(l)
        col.add_widget(button("Maine likh liya", then))

    # ----- PIN screen
    def pin_screen(self):
        self.unlocked = False
        self.lights.close()
        col = self.page("RGB Phone")
        self.pin_in = pin_field("PIN")
        col.add_widget(self.pin_in)
        self.msg_label(col)
        col.add_widget(button("Unlock", self.try_pin))
        col.add_widget(button("PIN bhool gaye? (recovery code)", self.forgot_screen,
                              font_size="14sp", background_color=GREY))
        self.watch_lock()

    def try_pin(self):
        ok, msg = sec.unlock(self.cfg, self.cfg_path, self.pin_in.text)
        self.pin_in.text = ""
        if not ok:
            self.msg.text = msg
            self.watch_lock()
            return
        self.unlocked = True
        if sec.needs_pairing(self.cfg):
            self.connection_screen(first=True)
        else:
            self.main_screen()

    # ----- forgot PIN: needs recovery code, NOT a free reset
    def forgot_screen(self):
        col = self.page("PIN reset")
        self.note(col, "Recovery code likho (setup ke time mila tha).")
        self.rec_in = field(hint_text="XXXX-XXXX-XXXX-XXXX-XXXX")
        col.add_widget(self.rec_in)
        self.n1 = pin_field("Naya PIN")
        self.n2 = pin_field("Naya PIN dobara")
        col.add_widget(self.n1)
        col.add_widget(self.n2)
        self.msg_label(col)
        col.add_widget(button("PIN reset karo", self.do_forgot))
        col.add_widget(button("Wapas", self.pin_screen, background_color=GREY))
        self.watch_lock()

    def do_forgot(self):
        if self.n1.text != self.n2.text:
            self.msg.text = "Dono PIN same nahi hain"
            return
        ok, msg, code = sec.reset_pin_with_recovery(self.cfg, self.cfg_path, self.rec_in.text,
                                                    self.n1.text)
        if not ok:
            self.msg.text = msg
            self.watch_lock()
            return
        self.recovery_screen(code, then=self.pin_screen)

    # ----- settings (every change needs the current PIN)
    def settings_screen(self):
        col = self.page("Settings")
        col.add_widget(button("PC / pairing badlo", self.connection_screen))
        col.add_widget(button("PIN badlo", self.change_pin_screen))
        col.add_widget(button("Naya recovery code", self.new_recovery_screen))
        col.add_widget(button("Wapas", self.main_screen, background_color=GREY))

    def connection_screen(self, first=False):
        col = self.page("PC / pairing")
        self.ip_in = field(text=self.cfg.get("host", ""), hint_text="PC IP")
        self.port_in = field(text=str(self.cfg.get("port", sec.DEFAULT_GATEWAY_PORT)),
                             hint_text="Port", input_filter="int")
        self.pair_in = field(hint_text="Naya pairing code (RGB1....)")
        for w in (self.ip_in, self.port_in, self.pair_in):
            col.add_widget(w)
        self.cur = pin_field("Abhi ka PIN")
        if not first:
            col.add_widget(self.cur)
        self.msg_label(col)
        col.add_widget(button("Save", lambda: self.save_connection(first)))
        if not first:
            col.add_widget(button("Wapas", self.settings_screen, background_color=GREY))

    def save_connection(self, first):
        err, host, port, pair = self.read_connection()
        if err:
            self.msg.text = err
            return
        if not first:
            ok, msg = sec.guarded_check(self.cfg, self.cfg_path, self.cfg.get("pin"), self.cur.text)
            if not ok:
                self.msg.text = msg
                return
        self.cfg.update({"host": host, "port": port, "pair": pair})
        sec.save_cfg(self.cfg_path, self.cfg)
        self.lights.close()
        self.main_screen()

    def change_pin_screen(self):
        col = self.page("PIN badlo")
        self.cur = pin_field("Abhi ka PIN")
        self.n1 = pin_field("Naya PIN")
        self.n2 = pin_field("Naya PIN dobara")
        for w in (self.cur, self.n1, self.n2):
            col.add_widget(w)
        self.msg_label(col)
        col.add_widget(button("Save", self.do_change_pin))
        col.add_widget(button("Wapas", self.settings_screen, background_color=GREY))

    def do_change_pin(self):
        if self.n1.text != self.n2.text:
            self.msg.text = "Dono PIN same nahi hain"
            return
        ok, msg, _ = sec.change_pin(self.cfg, self.cfg_path, self.cur.text, self.n1.text)
        if ok:
            self.settings_screen()
        else:
            self.msg.text = msg

    def new_recovery_screen(self):
        col = self.page("Naya recovery code")
        self.note(col, "Purana recovery code kaam karna band kar dega.")
        self.cur = pin_field("Abhi ka PIN")
        col.add_widget(self.cur)
        self.msg_label(col)
        col.add_widget(button("Naya code banao", self.do_new_recovery))
        col.add_widget(button("Wapas", self.settings_screen, background_color=GREY))

    def do_new_recovery(self):
        ok, msg, code = sec.rotate_recovery(self.cfg, self.cfg_path, self.cur.text)
        if ok:
            self.recovery_screen(code, then=self.settings_screen)
        else:
            self.msg.text = msg

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
        top.add_widget(button("Lock", self.pin_screen, size_hint_x=0.22, size_hint_y=1))
        top.add_widget(button("Settings", self.settings_screen, size_hint_x=0.3, size_hint_y=1))
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

    # ----- auto-lock when the app goes to background
    def on_pause(self):
        return True

    def on_resume(self):
        if self.unlocked and sec.is_configured(self.cfg):
            self.pin_screen()

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
