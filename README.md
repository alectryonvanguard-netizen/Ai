# QYRONEX AI — Android starter

QYRONEX AI is a Kivy Android app prototype with a five-second animated boot screen, a dashboard inspired by the supplied design, AI chat, local message history, adjustable AI instructions, and settings.

## Project files
- `main.py` — app source code
- `qyronex_logo.png` — QYRONEX brand artwork used on the splash and dashboard
- `requirements.txt` — Python development dependency
- `buildozer.spec` — Android APK packaging configuration
- `.github/workflows/build.yml` — GitHub Actions workflow for building a debug APK

## Build from a phone using GitHub
1. Create or open a GitHub repository in your mobile browser.
2. Upload the *contents* of this folder, including the hidden `.github/workflows/build.yml` path.
3. Commit to `main` (or `master`). Open the repository's **Actions** tab and select **Build QYRONEX AI APK**.
4. When the workflow completes, open its run summary and download the `qyronex-ai-debug-apk` artifact.

The workflow runs on GitHub's build server; you do not need to install Buildozer on your phone. It can take several minutes and may require toolchain updates if upstream Android build tools change.

## Test locally in Pydroid 3
Pydroid must have a compatible Kivy installation. Open `main.py` and run it. Building a distributable Android APK is more reliable through the included GitHub Actions workflow than directly on a phone.

## AI setup and safety
Open **Settings**, add your own Gemini API key, and save. Keep API keys private. A public app should send AI requests through a secure backend rather than shipping a shared API key in the APK.

## SAM NG integration status
The dashboard includes a **Connect SAM NG** entry point, but it is not a completed integration. A real connection needs the SAM NG app's documented API, backend URL, or supported Android deep link and an agreed authentication flow. This project does not pretend that connection is active yet.

## Current limitations
- Analytics cards analyze metrics that the user supplies; they do not fetch live campaign data.
- Sign-in to other apps requires each service's official authentication and permissions.
- Chat messages are saved locally in one history file; multiple independently restorable conversations are not implemented yet.
- Verify the splash animation, keyboard layout, API calls, and APK on a real Android phone before release.
