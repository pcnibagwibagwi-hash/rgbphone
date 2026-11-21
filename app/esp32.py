"""ESP32 smart-home remote: Light + Fan (relay) + RGB LED strip over the home Wi-Fi.

Talks to the web server in smart_home_esp32.ino:
  /light/on  /light/off  /fan/on  /fan/off  /rgb?r=&g=&b=  /rgb/off  /status
Plain standard library only (no extra packages needed in the APK).
"""
import json
import urllib.request

TIMEOUT = 3  # seconds; the ESP32 is on the same Wi-Fi, so it answers fast


class Esp32:
    def __init__(self, get_host, timeout=TIMEOUT):
        self.get_host = get_host
        self.timeout = timeout

    def _get(self, path):
        host = (self.get_host() or "").strip()
        if not host:
            raise ValueError("ESP32 ka IP likho")
        with urllib.request.urlopen("http://%s%s" % (host, path), timeout=self.timeout) as r:
            body = r.read().decode("utf-8", "replace")
        try:
            return json.loads(body)
        except ValueError:
            return {}

    def light(self, on):
        return self._get("/light/on" if on else "/light/off")

    def fan(self, on):
        return self._get("/fan/on" if on else "/fan/off")

    def rgb(self, rgb):
        r, g, b = (max(0, min(255, int(v))) for v in rgb)
        return self._get("/rgb?r=%d&g=%d&b=%d" % (r, g, b))

    def rgb_off(self):
        return self._get("/rgb/off")

    def status(self):
        return self._get("/status")
