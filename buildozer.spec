[app]
title = RGB Phone
package.name = rgbphone
package.domain = org.rgbphone
source.dir = app
source.include_exts = py
version = 2.1
requirements = python3,kivy==2.3.0,openrgb-python==0.3.8,openssl
orientation = portrait
fullscreen = 0

# Only INTERNET is needed (to talk to your PC). Nothing else is requested.
android.permissions = INTERNET
# Do not let Android/adb copy the app data (PIN hash, pairing secret) into backups
android.allow_backup = False
android.api = 33
android.minapi = 24
android.ndk = 25b
android.ndk_api = 24
android.archs = arm64-v8a
android.accept_sdk_license = True
android.release_artifact = apk
p4a.branch = v2024.01.21

[buildozer]
log_level = 2
warn_on_root = 1
