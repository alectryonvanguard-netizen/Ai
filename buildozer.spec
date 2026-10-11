[app]
title = QYRONEX AI
package.name = qyronexai
package.domain = org.qyronex
source.dir = .
source.include_exts = py,png,json,kv,txt
version = 0.2.0
requirements = python3,kivy
orientation = portrait
fullscreen = 0
presplash.filename = %(source.dir)s/logo.png
icon.filename = %(source.dir)s/icon.png

android.permissions = INTERNET
android.api = 33
android.minapi = 21
android.archs = arm64-v8a
android.accept_sdk_license = True
p4a.bootstrap = sdl2
android.ndk = 25b

[buildozer]
log_level = 2
warn_on_root = 1
