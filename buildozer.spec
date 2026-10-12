[app]
title = Ronex Ai
package.name = ronexai
package.domain = ai.ronex
source.dir = .
source.include_exts = py,png,json,kv,txt
version = 0.2.0
requirements = python3,kivy
orientation = portrait
fullscreen = 0
presplash.filename = logo.png
icon.filename = icon.png

android.permissions = INTERNET
android.api = 38
android.minapi = 36
android.archs = arm64-v8a
android.accept_sdk_license = True
p4a.bootstrap = sdl2
android.ndk = 25b
android.skip_update = False

[buildozer]
log_level = 2
warn_on_root = 1

