import traceback

CORE = r'''
"""RGB Phone - Android app that controls your PC's RGB lights through OpenRGB.

PC needs: OpenRGB running with its SDK server reachable on your Wi-Fi (port 6742).
The PIN only locks this app on your phone; OpenRGB itself has no password.
"""
import os
import json
import hashlib
import secrets
import threading

from kivy.app import App
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.slider import Slider
from kivy.uix.textinput import TextInput
from kivy.uix.colorpicker import ColorWheel

from openrgb import OpenRGBClient
from openrgb.utils import RGBColor

PORT = 6742
PRESETS = [
    ("Blue", (30, 64, 255)), ("Red", (225, 29, 29)), ("Green", (22, 163, 74)),
    ("Purple", (147, 51, 234)), ("Cyan", (8, 145, 178)), ("Orange", (249, 115, 22)),
    ("Pink", (236, 72, 153)), ("White", (255, 255, 255)),
]


# ------------------------------------------------------------------ logic ---
def hash_pin(pin, salt):
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), 100_000).hex()


def load_cfg(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cfg(path, cfg):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f)


def make_cfg(host, pin):
    salt = secrets.token_hex(16)
    return {"host": host.strip(), "salt": salt, "hash": hash_pin(pin, salt)}


def check_pin(cfg, pin):
    return bool(cfg.get("hash")) and hash_pin(pin, cfg["salt"]) == cfg["hash"]


class Lights:
    def __init__(self):
        self.client = None
        self.host = ""
        self.rgb = (30, 64, 255)
        self.bright = 100
        self.lock = threading.Lock()

    def connect(self, host):
        self.host = host
        self.client = OpenRGBClient(host, PORT, name="RGB Phone")
        return len(self.client.devices)

    def _ensure(self):
        if self.client is None:
            self.connect(self.host)

    def apply(self):
        with self.lock:
            self._ensure()
            f = self.bright / 100.0
            r, g, b = self.rgb
            try:
                self.client.set_color(RGBColor(int(r * f), int(g * f), int(b * f)))
            except Exception:
                self.client = None
                raise

    def set_rgb(self, rgb):
        self.rgb = tuple(int(v) for v in rgb)
        self.apply()

    def set_brightness(self, v):
        self.bright = max(0, min(100, int(v)))
        self.apply()

    def off(self):
        with self.lock:
            self._ensure()
            try:
                self.client.set_color(RGBColor(0, 0, 0))
            except Exception:
                self.client = None
                raise

    def rainbow(self):
        with self.lock:
            self._ensure()
            ok = False
            for d in self.client.devices:
                for m in d.modes:
                    if "rainbow" in m.name.lower() or "spectrum" in m.name.lower():
                        d.set_mode(m.name)
                        ok = True
                        break
            return ok


# --------------------------------------------------------------------- UI ---
def lbl(text, **kw):
    return Label(text=text, **kw)


class RGBPhoneApp(App):
    title = "RGB Phone"

    def build(self):
        from kivy.core.window import Window
        Window.clearcolor = (0.06, 0.06, 0.1, 1)
        self.lights = Lights()
        self.cfg_path = os.path.join(self.user_data_dir, "config.json")
        self.cfg = load_cfg(self.cfg_path)
        self.root_box = BoxLayout(orientation="vertical", padding=16, spacing=10)
        if not self.cfg.get("hash"):
            self.setup_screen()
        else:
            self.pin_screen()
        return self.root_box

    # ----- screens
    def setup_screen(self):
        r = self.root_box
        r.clear_widgets()
        r.add_widget(lbl("RGB Phone setup", font_size="26sp", size_hint_y=0.15))
        r.add_widget(lbl("PC ka IP address (jaise 192.168.1.8):", size_hint_y=0.07))
        self.ip_in = TextInput(text=self.cfg.get("host", "192.168.1.8"), multiline=False,
                               font_size="22sp", size_hint_y=0.1)
        r.add_widget(self.ip_in)
        r.add_widget(lbl("Apna PIN set karo (kam se kam 4 digits):", size_hint_y=0.07))
        self.pin1 = TextInput(password=True, multiline=False, font_size="22sp", size_hint_y=0.1,
                              input_filter="int")
        r.add_widget(self.pin1)
        self.msg = lbl("", color=(1, 0.45, 0.45, 1), size_hint_y=0.07)
        r.add_widget(self.msg)
        b = Button(text="Save", font_size="22sp", size_hint_y=0.13)
        b.bind(on_release=self.save_setup)
        r.add_widget(b)
        r.add_widget(lbl("", size_hint_y=0.2))

    def save_setup(self, *_):
        host, pin = self.ip_in.text.strip(), self.pin1.text
        if not host:
            self.msg.text = "IP likho"
        elif len(pin) < 4:
            self.msg.text = "PIN kam se kam 4 digits ka ho"
        else:
            self.cfg = make_cfg(host, pin)
            save_cfg(self.cfg_path, self.cfg)
            self.main_screen()

    def pin_screen(self):
        r = self.root_box
        r.clear_widgets()
        r.add_widget(lbl("RGB Phone", font_size="30sp", size_hint_y=0.3))
        self.pin_in = TextInput(hint_text="PIN", password=True, multiline=False, font_size="26sp",
                                size_hint_y=0.12, input_filter="int")
        r.add_widget(self.pin_in)
        self.msg = lbl("", color=(1, 0.45, 0.45, 1), size_hint_y=0.08)
        r.add_widget(self.msg)
        b = Button(text="Unlock", font_size="22sp", size_hint_y=0.15)
        b.bind(on_release=self.try_pin)
        r.add_widget(b)
        r.add_widget(lbl("", size_hint_y=0.3))

    def try_pin(self, *_):
        if check_pin(self.cfg, self.pin_in.text):
            self.main_screen()
        else:
            self.msg.text = "Galat PIN"

    def main_screen(self):
        r = self.root_box
        r.clear_widgets()
        top = BoxLayout(size_hint_y=0.07, spacing=8)
        self.status = lbl("Connecting...", halign="left")
        self.status.bind(size=lambda w, s: setattr(w, "text_size", s))
        top.add_widget(self.status)
        sb = Button(text="Setup", size_hint_x=0.25)
        sb.bind(on_release=lambda *_: self.setup_screen())
        top.add_widget(sb)
        r.add_widget(top)

        self.wheel = ColorWheel(size_hint_y=0.42)
        self.wheel.bind(color=self.on_wheel)
        r.add_widget(self.wheel)

        r.add_widget(lbl("Brightness", size_hint_y=0.04))
        sl = Slider(min=0, max=100, value=100, size_hint_y=0.07)
        sl.bind(value=self.on_bright)
        r.add_widget(sl)

        grid = GridLayout(cols=4, spacing=8, size_hint_y=0.18)
        for name, rgb in PRESETS:
            btn = Button(text=name, background_normal="", font_size="14sp",
                         background_color=(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, 1),
                         color=(0, 0, 0, 1) if name == "White" else (1, 1, 1, 1))
            btn.bind(on_release=lambda _b, c=rgb: self.run(self.lights.set_rgb, c))
            grid.add_widget(btn)
        r.add_widget(grid)

        row = BoxLayout(size_hint_y=0.12, spacing=10)
        rb = Button(text="Rainbow", font_size="20sp", background_color=(0.3, 0.2, 0.55, 1))
        rb.bind(on_release=lambda *_: self.run(self.lights.rainbow))
        ob = Button(text="Off", font_size="20sp", background_color=(0.2, 0.2, 0.2, 1))
        ob.bind(on_release=lambda *_: self.run(self.lights.off))
        row.add_widget(rb)
        row.add_widget(ob)
        r.add_widget(row)

        self.run(self.lights.connect, self.cfg["host"], note="Connected")

    # ----- actions (network calls run off the UI thread)
    def set_status(self, text):
        Clock.schedule_once(lambda dt: setattr(self.status, "text", text), 0)

    def run(self, fn, *args, note=None):
        def work():
            try:
                res = fn(*args)
                if note:
                    self.set_status("%s (%s devices)" % (note, res) if isinstance(res, int) else note)
                else:
                    self.set_status("OK")
            except Exception as e:
                self.set_status("Error: %s" % str(e)[:50])
        threading.Thread(target=work, daemon=True).start()

    def on_wheel(self, _w, color):
        self._pending = [int(c * 255) for c in color[:3]]
        Clock.unschedule(self._send_wheel)
        Clock.schedule_once(self._send_wheel, 0.1)

    def _send_wheel(self, _dt):
        self.run(self.lights.set_rgb, self._pending)

    def on_bright(self, _s, v):
        self._bright = v
        Clock.unschedule(self._send_bright)
        Clock.schedule_once(self._send_bright, 0.2)

    def _send_bright(self, _dt):
        self.run(self.lights.set_brightness, self._bright)


if __name__ == "__main__":
    RGBPhoneApp().run()

'''

try:
    ns = {"__name__": "rgbcore"}
    exec(compile(CORE, "rgbapp", "exec"), ns)
    ns["App"].run(ns["RGBPhoneApp"]())
except Exception:
    err = traceback.format_exc()
    from kivy.app import App
    from kivy.core.window import Window
    from kivy.uix.label import Label
    from kivy.uix.scrollview import ScrollView

    class ErrApp(App):
        def build(self):
            sv = ScrollView()
            lab = Label(text="ERROR (send screenshot):\n\n" + err,
                        size_hint_y=None, font_size="12sp",
                        halign="left", valign="top",
                        text_size=(Window.width - 20, None))
            lab.bind(texture_size=lambda w, s: setattr(w, "height", s[1] + 40))
            sv.add_widget(lab)
            return sv

    ErrApp().run()
