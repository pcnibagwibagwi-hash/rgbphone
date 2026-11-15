[app]
title = RGB Phone
package.name = rgbphone
package.domain = org.rgbphone
source.dir = .
source.include_exts = py
version = 1.0
requirements = python3,kivy==2.3.0,openrgb-python
orientation = portrait
fullscreen = 0
android.permissions = INTERNET
android.api = 33
android.minapi = 24
android.ndk = 25b
android.ndk_api = 24
android.archs = arm64-v8a
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 1
