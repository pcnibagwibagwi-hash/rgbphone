"""Launcher: if the app crashes on start, show the error on screen instead of closing."""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import rgbcore
    rgbcore.RGBPhoneApp().run()
except Exception:
    err = traceback.format_exc()
    from kivy.app import App
    from kivy.core.window import Window
    from kivy.uix.label import Label
    from kivy.uix.scrollview import ScrollView

    class ErrApp(App):
        def build(self):
            sv = ScrollView()
            lab = Label(text="ERROR (screenshot bhejo):\n\n" + err, size_hint_y=None,
                        font_size="12sp", halign="left", valign="top",
                        text_size=(Window.width - 20, None))
            lab.bind(texture_size=lambda w, s: setattr(w, "height", s[1] + 40))
            sv.add_widget(lab)
            return sv

    ErrApp().run()
