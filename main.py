"""
RONEX AI - Kivy app (v1.1)

Gemini key (never stored in the app UI, never commit it to GitHub). Provide it by:
  1) environment variable GEMINI_API_KEY, or
  2) gemini_key.txt next to this script (add it to .gitignore), or
  3) gemini_key.txt inside the app's user data folder.

Accounts are stored ON THIS DEVICE only (encrypted). For real multi-device accounts,
email/phone verification and password reset, you need a backend service.

Android build notes (Buildozer): requirements = python3,kivy,pyjnius,plyer,android
permissions = INTERNET,RECORD_AUDIO,READ_MEDIA_IMAGES,READ_MEDIA_VIDEO,READ_EXTERNAL_STORAGE,POST_NOTIFICATIONS
"""
import base64
import datetime
import hashlib
import hmac
import json
import math
import mimetypes
import os
import re
import threading
import time
import urllib.error
import urllib.request
import webbrowser

# ============================================================ SECURITY START
APP_VERSION = "1.1.0"
UPDATE_URL = ""          # link to a JSON file: {"version": "1.2.0", "notes": "...", "url": "https://..."}
TERMS_VERSION = "1"
NEWS_INTERVAL = 12 * 3600
PBKDF2_ROUNDS = 150000
COMMON_BITS = ("password", "qwerty", "123456", "letmein", "admin", "welcome", "iloveyou",
               "ronex", "abc123", "111111", "000000")


def normalize_identifier(raw):
    """Return ('email'|'phone', normalized) or (None, None)."""
    raw = (raw or "").strip()
    if "@" in raw:
        e = raw.lower()
        if re.fullmatch(r"[a-z0-9._%+\-]+@[a-z0-9\-]+(\.[a-z0-9\-]+)*\.[a-z]{2,}", e):
            return "email", e
        return None, None
    p = re.sub(r"[\s\-().]", "", raw)
    if re.fullmatch(r"\+?\d{8,15}", p):
        return "phone", p
    return None, None


def password_problems(pw, ident=""):
    probs = []
    if len(pw) < 10:
        probs.append("use at least 10 characters")
    if not re.search(r"[a-z]", pw):
        probs.append("add a lowercase letter")
    if not re.search(r"[A-Z]", pw):
        probs.append("add an uppercase letter")
    if not re.search(r"\d", pw):
        probs.append("add a number")
    if not re.search(r"[^A-Za-z0-9]", pw):
        probs.append("add a symbol like ! ? # $")
    low = pw.lower()
    if any(b in low for b in COMMON_BITS):
        probs.append("avoid common words or patterns")
    if re.search(r"(.)\1{3,}", pw):
        probs.append("avoid repeating one character")
    local = ident.split("@")[0].lower() if ident else ""
    digits = re.sub(r"\D", "", ident) if ident and "@" not in ident else ""
    if (len(local) >= 3 and local in low) or (len(digits) >= 6 and digits in re.sub(r"\D", "", pw)):
        probs.append("do not include your email name or phone number")
    return probs


def password_strength(pw, ident=""):
    classes = sum(bool(re.search(p, pw)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]"))
    score = (len(pw) >= 10) + (len(pw) >= 14) + (classes >= 3) + (classes == 4)
    if password_problems(pw, ident):
        score = min(score, 2)
    return score


def hash_password(pw, salt=None):
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return salt.hex(), dk.hex()


def verify_password(pw, salt_hex, hash_hex):
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), bytes.fromhex(salt_hex), PBKDF2_ROUNDS)
    return hmac.compare_digest(dk.hex(), hash_hex)


def _keys(master):
    return (hmac.new(master, b"ronex-enc", hashlib.sha256).digest(),
            hmac.new(master, b"ronex-mac", hashlib.sha256).digest())


def _stream(key, nonce, n):
    out = bytearray()
    c = 0
    while len(out) < n:
        out += hmac.new(key, nonce + c.to_bytes(8, "big"), hashlib.sha256).digest()
        c += 1
    return bytes(out[:n])


def encrypt_bytes(master, data):
    """Encrypt-then-MAC (HMAC-SHA256 counter keystream). Standard library only."""
    ek, mk = _keys(master)
    nonce = os.urandom(16)
    s = _stream(ek, nonce, len(data))
    ct = (int.from_bytes(data, "big") ^ int.from_bytes(s, "big")).to_bytes(len(data), "big") if data else b""
    tag = hmac.new(mk, b"R1" + nonce + ct, hashlib.sha256).digest()
    return b"R1" + nonce + ct + tag


def decrypt_bytes(master, blob):
    if len(blob) < 50 or blob[:2] != b"R1":
        raise ValueError("bad data")
    ek, mk = _keys(master)
    nonce, ct, tag = blob[2:18], blob[18:-32], blob[-32:]
    if not hmac.compare_digest(tag, hmac.new(mk, b"R1" + nonce + ct, hashlib.sha256).digest()):
        raise ValueError("data was modified or key is wrong")
    s = _stream(ek, nonce, len(ct))
    return (int.from_bytes(ct, "big") ^ int.from_bytes(s, "big")).to_bytes(len(ct), "big") if ct else b""


def load_master(folder):
    """Per-device random master key kept in the app's private folder."""
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "ronex_master.key")
    if os.path.exists(path):
        with open(path, "rb") as f:
            k = f.read()
        if len(k) == 32:
            return k
    k = os.urandom(32)
    with open(path, "wb") as f:
        f.write(k)
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass
    return k


def account_id(master, ident):
    return hmac.new(master, b"acct:" + ident.encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def write_secure(path, master, obj):
    blob = encrypt_bytes(master, json.dumps(obj, ensure_ascii=False).encode("utf-8"))
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(blob)
    os.replace(tmp, path)


def read_secure(path, master, default):
    try:
        with open(path, "rb") as f:
            return json.loads(decrypt_bytes(master, f.read()).decode("utf-8"))
    except Exception:
        return default


def ver_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v)))
# ============================================================== SECURITY END

from kivy.animation import Animation
from kivy.app import App
from kivy.clock import Clock
from kivy.core.clipboard import Clipboard
from kivy.core.window import Window
from kivy.graphics import Color, Ellipse, Line, Rectangle, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.properties import NumericProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.utils import get_color_from_hex

try:  # real voice input with volume callbacks (Android build with pyjnius)
    from jnius import PythonJavaClass, java_method, autoclass
    from android.runnable import run_on_ui_thread
    ANDROID_VOICE = True
except Exception:
    ANDROID_VOICE = False

APP_NAME = "Ronex AI"
DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_INSTRUCTIONS = (
    "You are Ronex AI, a helpful, friendly, honest personal marketing AI assistant inside the "
    "Ronex AI app. Answer clearly, adapt to the user's preferred style, ask a question when a "
    "request is unclear, and never pretend you completed an action that you did not complete."
)

BG = "#071026"
PANEL = "#12203F"
PANEL2 = "#1B2B50"
NAVBG = "#0A1530"
CYAN = "#20E4DC"
WHITE = "#F5F6FC"
MUTED = "#9FB0D0"
USER_BUBBLE = "#14485A"
BLUE, GREEN, YELLOW, RED = "#2D6BFF", "#1FAE62", "#F2B705", "#E04848"
PUBLIC = ("boot", "auth", "terms")

NAV = [("home", "Home"), ("campaigns", "Campaigns"), ("content", "Content"),
       ("analytics", "Analytics"), ("settings", "AI Settings")]
CONTENT_TYPES = [
    ("Social posts", "Write 3 social media posts (with hashtags and a call to action) about: "),
    ("Ad copy", "Write 3 ad copy variations (headline + body + call to action) for: "),
    ("Blog ideas", "Give 5 blog title ideas and a detailed outline for the best one about: "),
]

# Every section has its own chat: own persona, colours, greeting and starter prompts.
CHANNELS = {
    "main": dict(
        title="Ronex AI", sub="Marketing main", color=CYAN, bubble="#162447",
        greeting="Hi! I'm Ronex AI, your all-round marketing assistant. Ask me anything, or tap + to attach a photo or video.",
        persona="Role: all-round marketing assistant. Be friendly and conversational, give practical answers in plain language.",
        starters=["Give me 3 quick marketing wins for today", "How do I grow my brand on Instagram?",
                  "Help me write a short bio for my brand"]),
    "campaign": dict(
        title="Campaign Planner", sub="Strategy & plans", color=BLUE, bubble="#14285A",
        greeting="Campaign Planner here. Tell me your goal, audience and budget and I'll build a structured plan.",
        persona=("Role: senior campaign strategist. First ask for goal, audience, budget and timeline if missing. "
                 "Answer with structured plans: objective, audience, channels, phased timeline, budget split, KPIs. Be concise and decisive."),
        starters=["Plan a 2-week product launch campaign", "Split a small budget across 3 channels",
                  "Draft a one-month content calendar outline"]),
    "content": dict(
        title="Content Studio", sub="Posts, ads & blogs", color=GREEN, bubble="#10382B",
        greeting="Content Studio ready. Give me a topic and platform and I'll write ready-to-post drafts.",
        persona=("Role: creative copywriter. Produce ready-to-use drafts with a punchy voice, 2-3 variations, "
                 "hooks, hashtags and calls to action. Keep explanations minimal; lead with the copy."),
        starters=["Write 3 hooks for a product video", "Draft a LinkedIn post about my brand",
                  "Give me 10 hashtag ideas for my niche"]),
    "analytics": dict(
        title="Performance Analyst", sub="Data & results", color=YELLOW, bubble="#3B3010",
        greeting="Performance Analyst here. Paste your numbers (reach, clicks, sales...) and I'll tell you what they mean.",
        persona=("Role: marketing data analyst. Ask for the numbers if missing. Answer as: what the data shows, "
                 "likely causes, then 3 concrete actions. Be precise, skeptical, and never invent figures."),
        starters=["Which metrics matter most for a new brand?", "Help me understand a drop in engagement",
                  "Set 3 KPIs for next month"]),
    "insights": dict(
        title="Insights Coach", sub="Audience & trends", color=RED, bubble="#3C1A22",
        greeting="Insights Coach here. Let's find audiences, timing and trends worth acting on.",
        persona=("Role: insights coach. Give short, punchy, actionable insights about audiences, timing and trends. "
                 "Use quick bullet-style tips and end with one question that moves the user forward."),
        starters=["Which audience segments should I test?", "What are the best times to post this week?",
                  "What marketing trends should I watch?"]),
}

TERMS_TEXT = """Ronex AI - Terms & Conditions (version 1)

1. Your account. You sign up with an email address or phone number and a strong password. Keep your password private. You are responsible for activity on your account.

2. Data stored on this device. Your account, chats, campaigns and settings are stored in encrypted form in this app's private storage on your phone. Your password is never stored; only a salted hash of it is kept.

3. Backup after deletion. When you delete your account you can choose to keep an encrypted backup of your chat history on this device. If you later sign up again with the same email or phone number on this device, you will be asked whether to restore it. Choose "Delete everything" to remove it completely. Uninstalling the app removes all stored data.

4. AI service. Your messages, and any photos or videos you attach, are sent to Google's Gemini service to generate replies. Do not send information you are not allowed to share.

5. AI can be wrong. Replies may be inaccurate or out of date. Check important facts, numbers and legal or financial claims before acting on them.

6. Permissions. Access to photos, videos and the microphone is optional, is controlled in AI Settings, and is used only when you attach media or use voice typing.

7. Location news and updates. If notifications are on, the app uses your approximate location (from your internet connection) to ask the AI for local marketing news, and can tell you about app updates. You can switch both off in AI Settings.

8. Acceptable use. Do not use the app for unlawful, harmful, deceptive or abusive purposes, or to create spam or misleading advertising.

9. No guarantees. The app is provided "as is". Results from campaigns, content or analysis are not guaranteed.

10. Changes. These terms may change. You will be asked to accept new versions when they do.

By ticking the box you confirm you have read and accept these terms."""


def rgba(h):
    return get_color_from_hex(h)


def fmt_num(n):
    return f"{n/1000:.1f}K" if n >= 1000 else str(n)


def get_api_key(user_dir=""):
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key
    folders = []
    try:
        folders.append(os.path.dirname(os.path.abspath(__file__)))
    except Exception:
        pass
    if user_dir:
        folders.append(user_dir)
    for folder in folders:
        try:
            with open(os.path.join(folder, "gemini_key.txt"), "r", encoding="utf-8") as f:
                key = f.read().strip()
            if key:
                return key
        except Exception:
            pass
    return ""


def default_settings():
    return {"model": DEFAULT_MODEL, "instructions": DEFAULT_INSTRUCTIONS, "assistant_name": "Ronex AI",
            "user_name": "there", "temperature": 0.7, "prefs": [], "notify": True, "news": True,
            "media_ok": False, "mic_ok": False}


def default_data(settings):
    return {"settings": settings, "campaigns": [], "convs": [], "sent": 0, "day": "", "today": 0,
            "inbox": [], "last_news": 0, "last_update": 0, "location": ""}


# ----------------------------------------------------------------- widgets
class Card(BoxLayout):
    def __init__(self, bg=PANEL, radius=14, **kw):
        super().__init__(**kw)
        self._radius = dp(radius)
        self.set_bg(bg)
        self.bind(pos=self._upd, size=self._upd)

    def set_bg(self, hexc):
        self.canvas.before.clear()
        with self.canvas.before:
            Color(*rgba(hexc))
            self._rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[self._radius])

    def _upd(self, *_):
        self._rect.pos = self.pos
        self._rect.size = self.size


class Tile(ButtonBehavior, Card):
    """Tappable rounded panel."""


class TLabel(Label):
    def __init__(self, **kw):
        kw.setdefault("halign", "left")
        kw.setdefault("valign", "middle")
        kw.setdefault("color", rgba(WHITE))
        super().__init__(**kw)
        self.bind(size=lambda i, v: setattr(i, "text_size", (v[0], v[1])))


class AutoLabel(Label):
    def __init__(self, **kw):
        kw.setdefault("halign", "left")
        kw.setdefault("valign", "top")
        kw.setdefault("size_hint_y", None)
        kw.setdefault("color", rgba(WHITE))
        super().__init__(**kw)
        self.bind(width=lambda i, w: setattr(i, "text_size", (w, None)))
        self.bind(texture_size=lambda i, t: setattr(i, "height", t[1] + dp(2)))


class DotsIcon(Widget):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.bind(pos=self.draw, size=self.draw)

    def draw(self, *_):
        self.canvas.clear()
        d, gap = dp(7), dp(5)
        cx, cy = self.center
        with self.canvas:
            Color(*rgba(CYAN))
            for r in range(3):
                for c in range(2):
                    if r == 2 and c == 1:
                        continue
                    Ellipse(pos=(cx - d - gap / 2 + c * (d + gap), cy + (1 - r) * (d + gap) - d / 2), size=(d, d))


class BarsIcon(Widget):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.bind(pos=self.draw, size=self.draw)

    def draw(self, *_):
        self.canvas.clear()
        w, h, gap = dp(4), dp(22), dp(6)
        cx, cy = self.center
        with self.canvas:
            Color(*rgba(CYAN))
            for i in range(3):
                Rectangle(pos=(cx - 1.5 * w - gap + i * (w + gap), cy - h / 2), size=(w, h))


class LogoMark(Widget):
    angle = NumericProperty(0)

    def __init__(self, **kw):
        super().__init__(**kw)
        self.lbl = Label(text="[b]R[/b]", markup=True, color=rgba(CYAN))
        self.add_widget(self.lbl)
        self.bind(pos=self.draw, size=self.draw, angle=self.draw, parent=self._parent)
        anim = Animation(angle=360, duration=8)
        anim.repeat = True
        anim.start(self)

    def _parent(self, _i, p):
        if p is None:
            Animation.cancel_all(self)

    def draw(self, *_):
        self.canvas.before.clear()
        cx, cy = self.center
        r = min(self.width, self.height) / 2 * 0.92
        if r <= 0:
            return
        with self.canvas.before:
            Color(0.1, 0.9, 0.95, .14)
            Ellipse(pos=(cx - r * .85, cy - r * .85), size=(r * 1.7, r * 1.7))
            Color(*rgba(CYAN))
            Line(circle=(cx, cy, r), width=dp(2))
            Color(0.25, 0.55, 1, 1)
            Line(circle=(cx, cy, r * .74, self.angle, self.angle + 250), width=dp(3))
            Color(0.1, 1, .8, 1)
            Line(circle=(cx, cy, r * .52, -self.angle, -self.angle + 200), width=dp(2.5))
            Color(0.3, 0.9, 1, .35)
            Ellipse(pos=(cx - r * .28, cy - r * .28), size=(r * .56, r * .56))
        self.lbl.size = (r * 2, r * 2)
        self.lbl.center = self.center
        self.lbl.font_size = r * .55


class MicButton(ButtonBehavior, Card):
    """Microphone button drawn as a wave. While listening, bar height follows the real voice volume."""
    level = NumericProperty(0)

    def __init__(self, **kw):
        kw.setdefault("size_hint_x", None)
        kw.setdefault("width", dp(46))
        super().__init__(bg="#0F1B36", radius=14, **kw)
        self.listening = False
        self.target = 0.0
        self.phase = 0.0
        self._ev = None
        self.bind(pos=self.draw, size=self.draw, level=self.draw)
        self.draw()

    def set_listening(self, on):
        self.listening = on
        self.target = 0.0
        if on and not self._ev:
            self._ev = Clock.schedule_interval(self.tick, 1 / 30)
        if not on and self._ev:
            self._ev.cancel()
            self._ev = None
            self.level = 0
        self.draw()

    def tick(self, dt):
        self.phase += dt * 14
        self.level += (self.target - self.level) * .45

    def draw(self, *_):
        self.canvas.after.clear()
        mult = (.55, .85, 1, .85, .55)
        bw, gap = dp(4), dp(4)
        total = 5 * bw + 4 * gap
        x0, cy = self.center_x - total / 2, self.center_y
        maxh, minh = self.height * .62, dp(6)
        with self.canvas.after:
            Color(*rgba("#FF5A6A" if self.listening else CYAN))
            for i in range(5):
                if self.listening:
                    wob = .75 + .25 * math.sin(self.phase + i * 1.3)
                    h = minh + (maxh - minh) * max(self.level, .04) * mult[i] * wob
                else:
                    h = minh + (maxh - minh) * .35 * mult[i]
                Rectangle(pos=(x0 + i * (bw + gap), cy - h / 2), size=(bw, h))


if ANDROID_VOICE:
    class _Listener(PythonJavaClass):
        __javainterfaces__ = ["android/speech/RecognitionListener"]
        __javacontext__ = "app"

        def __init__(self, on_rms, on_text, on_end):
            super().__init__()
            self.on_rms, self.on_text, self.on_end = on_rms, on_text, on_end

        def _text(self, bundle):
            r = bundle.getStringArrayList("results_recognition")
            return str(r.get(0)) if r is not None and r.size() else ""

        @java_method("()V")
        def onBeginningOfSpeech(self):
            pass

        @java_method("([B)V")
        def onBufferReceived(self, b):
            pass

        @java_method("()V")
        def onEndOfSpeech(self):
            pass

        @java_method("(I)V")
        def onError(self, e):
            self.on_end()

        @java_method("(ILandroid/os/Bundle;)V")
        def onEvent(self, t, b):
            pass

        @java_method("(Landroid/os/Bundle;)V")
        def onPartialResults(self, b):
            self.on_text(self._text(b), False)

        @java_method("(Landroid/os/Bundle;)V")
        def onReadyForSpeech(self, b):
            pass

        @java_method("(Landroid/os/Bundle;)V")
        def onResults(self, b):
            self.on_text(self._text(b), True)

        @java_method("(F)V")
        def onRmsChanged(self, rms):
            self.on_rms(rms)


class VoiceInput:
    """Speech-to-text into a TextInput with a live volume wave on the mic button."""
    def __init__(self, app):
        self.app = app
        self.mic = self.target = self.sr = self.listener = None
        self.base = ""

    def toggle(self, mic, target):
        if self.mic is mic:
            self.stop()
            return
        self.stop()
        if not ANDROID_VOICE:
            self.app.notice("Voice typing", "Voice typing needs the Android app build (Buildozer APK with pyjnius). "
                                            "Inside Pydroid, use the microphone key on your keyboard instead.")
            return
        self.app.ensure_perm("mic", cb=lambda: self.begin(mic, target))

    def begin(self, mic, target):
        self.mic, self.target = mic, target
        self.base = target.text.strip()
        mic.set_listening(True)
        self._start_ui()

    @run_on_ui_thread if ANDROID_VOICE else (lambda f: f)
    def _start_ui(self):
        try:
            act = autoclass("org.kivy.android.PythonActivity").mActivity
            SR = autoclass("android.speech.SpeechRecognizer")
            Intent = autoclass("android.content.Intent")
            RS = autoclass("android.speech.RecognizerIntent")
            self.sr = SR.createSpeechRecognizer(act)
            self.listener = _Listener(self._rms, self._text, self._ended)
            self.sr.setRecognitionListener(self.listener)
            intent = Intent(RS.ACTION_RECOGNIZE_SPEECH)
            intent.putExtra(RS.EXTRA_LANGUAGE_MODEL, RS.LANGUAGE_MODEL_FREE_FORM)
            intent.putExtra(RS.EXTRA_PARTIAL_RESULTS, True)
            self.sr.startListening(intent)
        except Exception:
            Clock.schedule_once(lambda *_: self._ended(), 0)

    def _rms(self, rms):
        lvl = max(0.0, min(1.0, (float(rms) + 2) / 12))
        Clock.schedule_once(lambda *_: setattr(self.mic, "target", lvl) if self.mic else None, 0)

    def _text(self, txt, final):
        def apply(*_):
            if self.target is not None and txt:
                self.target.text = (self.base + " " + txt).strip()
            if final:
                self.stop()
        Clock.schedule_once(apply, 0)

    def _ended(self):
        Clock.schedule_once(lambda *_: self.stop(), 0)

    def stop(self):
        mic, sr = self.mic, self.sr
        self.mic = self.target = self.sr = self.listener = None
        if mic:
            mic.set_listening(False)
        if sr is not None and ANDROID_VOICE:
            self._release(sr)

    @run_on_ui_thread if ANDROID_VOICE else (lambda f: f)
    def _release(self, sr):
        try:
            sr.stopListening()
            sr.destroy()
        except Exception:
            pass


PERMS = {
    "media": ["android.permission.READ_MEDIA_IMAGES", "android.permission.READ_MEDIA_VIDEO",
              "android.permission.READ_EXTERNAL_STORAGE"],
    "mic": ["android.permission.RECORD_AUDIO"],
    "notify": ["android.permission.POST_NOTIFICATIONS"],
}


# -------------------------------------------------------------------- app
class RonexAIApp(App):
    def build(self):
        self.title = APP_NAME
        Window.clearcolor = rgba(BG)
        try:
            Window.softinput_mode = "pan"
        except Exception:
            pass
        self.master = load_master(self.user_data_dir)
        self.vault_path = os.path.join(self.user_data_dir, "ronex_accounts.dat")
        self.vault = read_secure(self.vault_path, self.master, None) or {}
        self.vault.setdefault("accounts", {})
        self.vault.setdefault("terms", {})
        self.vault.setdefault("session", None)
        self.acct = None
        self.acct_id = None
        self.settings = default_settings()
        self.data = default_data(self.settings)
        self.cur = {}
        self.channel = "main"
        self.busy = False
        self.news_busy = False
        self.pending = None
        self.pending_image = None
        self.ctype = 0
        self.auth_mode = "login"
        self.auth_id = ""
        self.screen = "boot"
        self.voice = VoiceInput(self)
        root = BoxLayout(orientation="vertical")
        self.body = BoxLayout()
        root.add_widget(self.body)
        self.nav = BoxLayout(size_hint_y=None, height=0, opacity=0, spacing=dp(3), padding=(dp(4), dp(3)))
        root.add_widget(self.nav)
        self.nav_tiles = {}
        for key, label in NAV:
            t = Tile(bg=NAVBG, radius=10)
            t.lbl = TLabel(text=label, halign="center", font_size=sp(11), color=rgba(MUTED))
            t.add_widget(t.lbl)
            t.bind(on_release=lambda _i, k=key: self.go(k))
            self.nav.add_widget(t)
            self.nav_tiles[key] = t
        self.build_boot()
        Clock.schedule_once(lambda *_: self.start_flow(), 3)
        return root

    # ----------------------------------------------------- storage/accounts
    def user_path(self, aid):
        return os.path.join(self.user_data_dir, f"ronex_u_{aid}.dat")

    def backup_path(self, aid):
        return os.path.join(self.user_data_dir, f"ronex_bk_{aid}.dat")

    def save_vault(self):
        try:
            write_secure(self.vault_path, self.master, self.vault)
        except Exception as exc:
            self.notice("Could not save account data", str(exc))

    def save_data(self):
        if not self.acct_id:
            return
        try:
            self.data["convs"] = self.data["convs"][-40:]
            for c in self.data["convs"]:
                c["messages"] = c["messages"][-120:]
            self.data["settings"] = self.settings
            write_secure(self.user_path(self.acct_id), self.master, self.data)
        except Exception:
            pass

    save_settings = save_data

    def begin_session(self, aid):
        self.acct_id = aid
        self.acct = self.vault["accounts"][aid]
        d = read_secure(self.user_path(aid), self.master, None)
        settings = default_settings()
        data = default_data(settings)
        if isinstance(d, dict):
            for k in data:
                if k != "settings" and k in d:
                    data[k] = d[k]
            if isinstance(d.get("settings"), dict):
                settings.update({k: v for k, v in d["settings"].items() if k in settings})
        for c in data["convs"]:
            c.setdefault("channel", "main")
        data["settings"] = settings
        self.settings, self.data, self.cur = settings, data, {}
        self.vault["session"] = aid
        self.save_vault()

    def end_session(self):
        self.voice.stop()
        self.vault["session"] = None
        self.save_vault()
        self.acct = self.acct_id = None
        self.settings = default_settings()
        self.data = default_data(self.settings)
        self.cur = {}
        self.pending_image = None

    def on_stop(self):
        self.save_data()
        self.save_vault()

    def start_flow(self):
        aid = self.vault.get("session")
        if aid and aid in self.vault["accounts"]:
            if self.vault["terms"].get(aid) == TERMS_VERSION:
                self.begin_session(aid)
                self.go("home")
                self.post_login()
                return
            self.pending = {"mode": "login", "aid": aid}
            self.go("terms")
            return
        self.go("auth")

    def post_login(self):
        Clock.schedule_once(lambda *_: self.check_updates(False), 2)
        Clock.schedule_once(lambda *_: self.refresh_news(False), 4)

    def finish_login(self, aid, new=False, note=None):
        self.begin_session(aid)
        if new and self.settings.get("user_name") in (None, "", "there"):
            ident = self.acct.get("ident", "")
            if self.acct.get("ptype") == "email":
                self.settings["user_name"] = re.sub(r"[^A-Za-z]", " ", ident.split("@")[0]).split()[0].title() \
                    if re.search(r"[A-Za-z]", ident.split("@")[0]) else "there"
        self.save_data()
        self.go("home")
        self.post_login()
        if note:
            Clock.schedule_once(lambda *_: self.notice("Welcome back", note), .5)

    def logout(self, mode="login"):
        self.end_session()
        self.auth_mode = mode
        self.auth_id = ""
        self.go("auth")

    # ------------------------------------------------------------ helpers
    def ti_style(self, bg=PANEL2):
        return dict(background_normal="", background_active="",
                    background_color=bg if isinstance(bg, (tuple, list)) else rgba(bg),
                    foreground_color=rgba(WHITE), hint_text_color=rgba(MUTED),
                    cursor_color=rgba(CYAN), padding=(dp(12), dp(10)), font_size=sp(15))

    def btn(self, text, cb=None, bg=PANEL2, fg=WHITE, fs=14, **kw):
        t = Tile(bg=bg, padding=dp(4), **kw)
        t.lbl = TLabel(text=text, halign="center", color=rgba(fg), font_size=sp(fs), bold=True)
        t.add_widget(t.lbl)
        if cb:
            t.bind(on_release=cb)
        return t

    def mic_for(self, ti):
        mic = MicButton()
        mic.bind(on_release=lambda *_: self.voice.toggle(mic, ti))
        return mic

    def with_mic(self, ti, **kw):
        row = BoxLayout(spacing=dp(6), **kw)
        row.add_widget(ti)
        row.add_widget(self.mic_for(ti))
        return row

    def page(self, pad=(12, 8)):
        p = BoxLayout(orientation="vertical", padding=(dp(pad[0]), dp(pad[1])), spacing=dp(8))
        self.body.add_widget(p)
        return p

    def header(self, title, chat=None):
        row = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(8))
        row.add_widget(self.btn("<", lambda *_: self.go("home"), fs=18, size_hint=(None, 1), width=dp(46)))
        row.add_widget(TLabel(text=f"[b]{title}[/b]", markup=True, font_size=sp(20)))
        if chat:
            ch = CHANNELS[chat]
            row.add_widget(self.btn("Chat", lambda *_: self.open_chat(channel=chat), bg=ch["color"], fg=BG, fs=13,
                                    size_hint=(None, 1), width=dp(64)))
        return row

    def logo(self, **kw):
        try:
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ronex_logo.png")
        except Exception:
            path = ""
        if path and os.path.exists(path):
            return Image(source=path, allow_stretch=True, keep_ratio=True, **kw)
        return LogoMark(**kw)

    def go(self, name):
        if name not in PUBLIC and not self.acct_id:
            name = "auth"
        self.voice.stop()
        self.screen = name
        self.body.clear_widgets()
        show = name not in PUBLIC
        self.nav.height = dp(54) if show else 0
        self.nav.opacity = 1 if show else 0
        getattr(self, "build_" + name)()
        for k, t in self.nav_tiles.items():
            t.lbl.color = rgba(CYAN if k == name else MUTED)
        Window.release_all_keyboards()

    def notice(self, title, message):
        box = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(12))
        box.add_widget(TLabel(text=message, halign="center", font_size=sp(14)))
        ok = self.btn("OK", None, bg=CYAN, fg=BG, size_hint_y=None, height=dp(44))
        box.add_widget(ok)
        pop = Popup(title=title, content=box, size_hint=(.88, .45), background_color=rgba(PANEL))
        ok.bind(on_release=pop.dismiss)
        pop.open()

    def menu_popup(self, title, items):
        box = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        pop = Popup(title=title, content=box, size_hint=(.86, None),
                    height=dp(110 + 54 * len(items)), background_color=rgba(PANEL))
        for label, cb in items:
            b = self.btn(label, None, size_hint_y=None, height=dp(46))
            b.bind(on_release=lambda _i, cb=cb: (pop.dismiss(), cb()))
            box.add_widget(b)
        box.add_widget(self.btn("Close", pop.dismiss, bg=PANEL, fg=MUTED, size_hint_y=None, height=dp(40)))
        pop.open()

    def ensure_perm(self, kind, cb=None, after=None):
        flag = kind + "_ok"

        def done(granted):
            if kind != "notify":
                self.settings[flag] = bool(granted)
                self.save_data()
            if granted and cb:
                cb()
            elif not granted:
                self.notice("Permission needed", "Permission was not granted. You can allow it in AI Settings "
                                                 "or in your phone's app settings.")
            if after:
                after()
        try:
            from android.permissions import request_permissions

            def result(_perms, grants):
                Clock.schedule_once(lambda *_: done(any(grants)), 0)
            request_permissions(PERMS[kind], result)
        except Exception:  # not an Android build: just switch the in-app permission on
            done(True)

    # --------------------------------------------------------------- boot
    def build_boot(self):
        self.body.clear_widgets()
        p = BoxLayout(orientation="vertical", padding=dp(20), spacing=dp(10))
        p.add_widget(Widget())
        p.add_widget(self.logo(size_hint_y=None, height=min(Window.width * .7, dp(280))))
        p.add_widget(TLabel(text="[b]RONEX AI[/b]", markup=True, halign="center", color=rgba(CYAN),
                            font_size=sp(34), size_hint_y=None, height=dp(50)))
        p.add_widget(TLabel(text="AI ASSISTANT  -  INITIALIZING", halign="center", color=rgba(MUTED),
                            font_size=sp(12), size_hint_y=None, height=dp(24)))
        p.add_widget(Widget())
        self.body.add_widget(p)

    # --------------------------------------------------- auth (login/signup)
    def switch_auth(self, mode):
        self.auth_mode = mode
        self.go("auth")

    def build_auth(self):
        mode = self.auth_mode
        sv = ScrollView(do_scroll_x=False, bar_width=0)
        col = BoxLayout(orientation="vertical", size_hint_y=None, padding=(dp(20), dp(16)), spacing=dp(10))
        col.bind(minimum_height=col.setter("height"))
        col.add_widget(LogoMark(size_hint_y=None, height=dp(130)))
        col.add_widget(TLabel(text="[b]RONEX AI[/b]", markup=True, halign="center", color=rgba(CYAN),
                              font_size=sp(30), size_hint_y=None, height=dp(44)))
        col.add_widget(TLabel(text="Log in to continue" if mode == "login" else "Create your account",
                              halign="center", color=rgba(MUTED), font_size=sp(14), size_hint_y=None, height=dp(24)))
        tabs = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        for m, label in (("login", "Log in"), ("signup", "Sign up")):
            on = m == mode
            tabs.add_widget(self.btn(label, lambda *_, m=m: self.switch_auth(m),
                                     bg=CYAN if on else PANEL2, fg=BG if on else WHITE))
        col.add_widget(tabs)
        ti = self.ti_style()
        idf = TextInput(text=self.auth_id, hint_text="Email or phone number", multiline=False,
                        size_hint_y=None, height=dp(50), write_tab=False, **ti)
        col.add_widget(idf)
        pw_row = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(6))
        pw = TextInput(hint_text="Password", password=True, multiline=False, write_tab=False, **ti)
        pw_row.add_widget(pw)
        confirm = None
        if mode == "signup":
            confirm = TextInput(hint_text="Confirm password", password=True, multiline=False,
                                size_hint_y=None, height=dp(50), write_tab=False, **ti)

        def toggle_show(*_):
            pw.password = not pw.password
            if confirm:
                confirm.password = pw.password
            show.lbl.text = "Hide" if not pw.password else "Show"
        show = self.btn("Show", toggle_show, fs=12, size_hint_x=None, width=dp(62))
        pw_row.add_widget(show)
        col.add_widget(pw_row)
        strength = AutoLabel(text="", font_size=sp(12), color=rgba(MUTED))
        if mode == "signup":
            col.add_widget(confirm)
            col.add_widget(strength)
            col.add_widget(AutoLabel(text="Password rules: 10+ characters with upper and lower case, a number and a symbol.",
                                     font_size=sp(11), color=rgba(MUTED)))

            def upd(*_):
                ident = normalize_identifier(idf.text)[1] or ""
                score = password_strength(pw.text, ident)
                probs = password_problems(pw.text, ident)
                names = ["Too weak", "Weak", "Fair", "Good", "Strong"]
                cols = [RED, RED, YELLOW, GREEN, GREEN]
                strength.text = (f"Strength: {names[score]}" if pw.text else "") + \
                                (f" - {probs[0]}" if probs and pw.text else "")
                strength.color = rgba(cols[score])
            pw.bind(text=upd)
            idf.bind(text=upd)
        err = AutoLabel(text="", font_size=sp(13), color=rgba("#FF8A8A"))
        col.add_widget(err)

        def submit(*_):
            self.auth_id = idf.text
            msg = self.do_signup(idf.text, pw.text, confirm.text) if mode == "signup" else self.do_login(idf.text, pw.text)
            if msg:
                err.text = msg
        pw.bind(on_text_validate=submit)
        col.add_widget(self.btn("Log in" if mode == "login" else "Create account", submit, bg=CYAN, fg=BG,
                                size_hint_y=None, height=dp(52)))
        col.add_widget(AutoLabel(text="Your account is stored encrypted on this device. There is no guest mode: "
                                      "you must log in or sign up to use Ronex AI.",
                                 font_size=sp(11), color=rgba(MUTED), halign="center"))
        sv.add_widget(col)
        self.body.add_widget(sv)
        col.opacity = 0
        Animation(opacity=1, duration=.9, t="out_quad").start(col)

    def do_login(self, raw_id, password):
        ptype, ident = normalize_identifier(raw_id)
        if not ident:
            return "Enter a valid email address or phone number."
        aid = account_id(self.master, ident)
        acc = self.vault["accounts"].get(aid)
        if not acc:
            return "No account found for that email or phone. Please sign up first."
        wait = int(acc.get("lock_until", 0) - time.time())
        if wait > 0:
            return f"Too many wrong attempts. Try again in {wait} seconds."
        if not password or not verify_password(password, acc["salt"], acc["hash"]):
            acc["fails"] = acc.get("fails", 0) + 1
            if acc["fails"] >= 5:
                acc["lock_until"] = time.time() + min(900, 30 * 2 ** (acc["fails"] - 5))
            self.save_vault()
            return "Wrong password."
        acc["fails"], acc["lock_until"] = 0, 0
        self.save_vault()
        if self.vault["terms"].get(aid) == TERMS_VERSION:
            self.finish_login(aid)
        else:
            self.pending = {"mode": "login", "aid": aid}
            self.go("terms")
        return ""

    def do_signup(self, raw_id, password, confirm):
        ptype, ident = normalize_identifier(raw_id)
        if not ident:
            return "Enter a valid email address or phone number (8-15 digits, optional +)."
        aid = account_id(self.master, ident)
        if aid in self.vault["accounts"]:
            return "An account already exists for that email or phone. Please log in."
        probs = password_problems(password, ident)
        if probs:
            return "Password is not strong enough: " + "; ".join(probs[:3]) + "."
        if password != confirm:
            return "Passwords do not match."
        self.pending = {"mode": "signup", "ident": ident, "ptype": ptype, "pw": password}
        self.go("terms")
        return ""

    # -------------------------------------------------------------- terms
    def build_terms(self):
        p = self.page((14, 10))
        p.add_widget(TLabel(text="[b]Terms & Conditions[/b]", markup=True, font_size=sp(22),
                            size_hint_y=None, height=dp(44)))
        wrap = Card(bg=PANEL, padding=dp(10))
        sv = ScrollView(do_scroll_x=False)
        sv.add_widget(AutoLabel(text=TERMS_TEXT, font_size=sp(13)))
        wrap.add_widget(sv)
        p.add_widget(wrap)
        state = {"on": False}
        chk = Tile(bg=PANEL2, size_hint_y=None, height=dp(52), padding=dp(10))
        lbl = TLabel(text="[  ]  I have read and accept the Terms & Conditions", font_size=sp(13))
        chk.add_widget(lbl)

        def toggle(*_):
            state["on"] = not state["on"]
            lbl.text = ("[x]" if state["on"] else "[  ]") + "  I have read and accept the Terms & Conditions"
        chk.bind(on_release=toggle)
        p.add_widget(chk)
        row = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(8))

        def accept(*_):
            if not state["on"]:
                self.notice("Terms", "Tick the box to accept the Terms & Conditions before you can log in.")
                return
            self.accept_terms()

        def decline(*_):
            self.pending = None
            self.go("auth")
        row.add_widget(self.btn("Accept & continue", accept, bg=CYAN, fg=BG))
        row.add_widget(self.btn("Decline", decline, size_hint_x=.5))
        p.add_widget(row)

    def accept_terms(self):
        pend = self.pending
        self.pending = None
        if not pend:
            self.go("auth")
            return
        if pend["mode"] == "login":
            aid = pend["aid"]
            if aid not in self.vault["accounts"]:
                self.go("auth")
                return
            self.vault["terms"][aid] = TERMS_VERSION
            self.save_vault()
            self.finish_login(aid)
            return
        ident = pend["ident"]
        aid = account_id(self.master, ident)
        if aid in self.vault["accounts"]:
            self.go("auth")
            return
        salt, h = hash_password(pend["pw"])
        pend["pw"] = None
        self.vault["accounts"][aid] = {"ident": ident, "ptype": pend["ptype"], "salt": salt, "hash": h,
                                       "created": datetime.datetime.now().isoformat(timespec="seconds"),
                                       "fails": 0, "lock_until": 0}
        self.vault["terms"][aid] = TERMS_VERSION
        self.save_vault()
        if os.path.exists(self.backup_path(aid)):
            self.ask_restore(aid)
        else:
            self.finish_login(aid, new=True)

    def ask_restore(self, aid):
        box = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(10))
        box.add_widget(TLabel(text="We found an encrypted backup of the chat history from an account you "
                                   "previously deleted with this email/phone on this device. Restore it?",
                              halign="center", font_size=sp(14)))
        pop = Popup(title="Restore your history?", content=box, size_hint=(.9, .5), auto_dismiss=False,
                    background_color=rgba(PANEL))

        def restore(*_):
            pop.dismiss()
            try:
                os.replace(self.backup_path(aid), self.user_path(aid))
            except Exception:
                pass
            self.begin_session(aid)
            n, m = len(self.data["convs"]), len(self.data["campaigns"])
            self.finish_login(aid, note=f"Restored {n} chat(s) and {m} campaign(s) from your backup.")

        def fresh(*_):
            pop.dismiss()
            try:
                os.remove(self.backup_path(aid))
            except Exception:
                pass
            self.finish_login(aid, new=True)
        box.add_widget(self.btn("Restore my chat history", restore, bg=CYAN, fg=BG, size_hint_y=None, height=dp(48)))
        box.add_widget(self.btn("Start fresh (delete backup)", fresh, bg=RED, size_hint_y=None, height=dp(48)))
        pop.open()

    def confirm_delete(self):
        box = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
        pop = Popup(title="Delete account", content=box, size_hint=(.92, .65), background_color=rgba(PANEL))
        box.add_widget(TLabel(text="Enter your password to confirm. You can keep an encrypted backup of your "
                                   "chat history on this device so it can be restored if you sign up again.",
                              font_size=sp(13), size_hint_y=None, height=dp(78)))
        pw = TextInput(hint_text="Password", password=True, multiline=False, size_hint_y=None, height=dp(48),
                       write_tab=False, **self.ti_style())
        box.add_widget(pw)
        err = TLabel(text="", color=rgba("#FF8A8A"), font_size=sp(12), size_hint_y=None, height=dp(22))
        box.add_widget(err)

        def go_del(keep):
            if not verify_password(pw.text, self.acct["salt"], self.acct["hash"]):
                err.text = "Wrong password."
                return
            pop.dismiss()
            self.delete_account(keep)
        box.add_widget(self.btn("Delete, keep encrypted backup", lambda *_: go_del(True), size_hint_y=None, height=dp(46)))
        box.add_widget(self.btn("Delete everything", lambda *_: go_del(False), bg=RED, size_hint_y=None, height=dp(46)))
        box.add_widget(self.btn("Cancel", pop.dismiss, bg=PANEL, fg=MUTED, size_hint_y=None, height=dp(40)))
        pop.open()

    def delete_account(self, keep):
        aid = self.acct_id
        self.save_data()
        up, bk = self.user_path(aid), self.backup_path(aid)
        try:
            if keep and os.path.exists(up):
                os.replace(up, bk)
            else:
                for f in (up, bk):
                    if os.path.exists(f):
                        os.remove(f)
        except Exception:
            pass
        self.vault["accounts"].pop(aid, None)
        self.vault["terms"].pop(aid, None)
        self.end_session()
        self.auth_mode = "signup"
        self.go("auth")
        self.notice("Account deleted", "Your account was deleted. " +
                    ("An encrypted backup of your chat history was kept on this device." if keep
                     else "All your data was removed."))

    # --------------------------------------------------- notifications/news
    def add_inbox(self, title, body):
        self.data["inbox"].insert(0, {"title": title, "body": body, "ts": time.time(), "read": False})
        self.data["inbox"] = self.data["inbox"][:50]
        self.save_data()

    def push_notification(self, title, msg):
        try:
            from plyer import notification
            notification.notify(title=title, message=msg[:200], app_name=APP_NAME, timeout=8)
        except Exception:
            pass

    def show_inbox(self):
        box = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        pop = Popup(title="Inbox", content=box, size_hint=(.94, .85), background_color=rgba(PANEL))
        sv = ScrollView(do_scroll_x=False)
        grid = GridLayout(cols=1, size_hint_y=None, spacing=dp(8))
        grid.bind(minimum_height=grid.setter("height"))
        items = self.data["inbox"]
        if not items:
            grid.add_widget(AutoLabel(text="No messages yet. Updates and local news will appear here.",
                                      color=rgba(MUTED)))
        for it in items:
            c = Card(bg=PANEL2, orientation="vertical", size_hint_y=None, padding=dp(10), spacing=dp(4))
            c.bind(minimum_height=c.setter("height"))
            when = datetime.datetime.fromtimestamp(it["ts"]).strftime("%d %b %H:%M")
            c.add_widget(AutoLabel(text=f"[b]{it['title']}[/b]  [size=11sp]{when}[/size]", markup=True,
                                   color=rgba(CYAN), font_size=sp(13)))
            c.add_widget(AutoLabel(text=it["body"], font_size=sp(13)))
            grid.add_widget(c)
            it["read"] = True
        self.save_data()
        sv.add_widget(grid)
        box.add_widget(sv)
        row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))

        def clear(*_):
            self.data["inbox"] = []
            self.save_data()
            pop.dismiss()
        row.add_widget(self.btn("Clear all", clear, bg=RED))
        row.add_widget(self.btn("Close", pop.dismiss))
        box.add_widget(row)
        pop.open()

    def unread(self):
        return sum(1 for i in self.data["inbox"] if not i.get("read"))

    def check_updates(self, manual=False):
        if not self.acct_id:
            return
        if not UPDATE_URL:
            if manual:
                self.notice("Updates", "No update link is set. Put the link to your update JSON file in "
                                       "UPDATE_URL at the top of the code.")
            return
        if not manual and (not self.settings.get("notify") or time.time() - self.data.get("last_update", 0) < NEWS_INTERVAL):
            return

        def work():
            info = None
            try:
                req = urllib.request.Request(UPDATE_URL, headers={"User-Agent": "RONEX/" + APP_VERSION})
                with urllib.request.urlopen(req, timeout=10) as r:
                    info = json.loads(r.read().decode("utf-8"))
            except Exception:
                pass
            Clock.schedule_once(lambda *_: self.on_update_info(info, manual), 0)
        threading.Thread(target=work, daemon=True).start()

    def on_update_info(self, info, manual):
        if not self.acct_id:
            return
        self.data["last_update"] = time.time()
        if not info or "version" not in info:
            if manual:
                self.notice("Updates", "Could not check for updates. Check your internet connection.")
            return
        if ver_tuple(info["version"]) > ver_tuple(APP_VERSION):
            notes = info.get("notes", "")
            self.add_inbox(f"Update available: v{info['version']}", (notes + "\n" + info.get("url", "")).strip())
            self.push_notification("Ronex AI update", f"Version {info['version']} is available.")
            url = info.get("url")
            items = [("Open download page", lambda: webbrowser.open(url))] if url else []
            if items:
                self.menu_popup(f"Update v{info['version']} available", items)
            else:
                self.notice("Update available", f"Version {info['version']} is available.\n{notes}")
        elif manual:
            self.notice("Updates", f"You are up to date (v{APP_VERSION}).")
        self.save_data()

    def refresh_news(self, manual=False):
        s = self.settings
        if not self.acct_id or self.news_busy:
            return
        if not manual and (not s.get("notify") or not s.get("news") or
                           time.time() - self.data.get("last_news", 0) < NEWS_INTERVAL):
            return
        self.news_busy = True

        def locate():
            loc = ""
            try:
                req = urllib.request.Request("https://ipapi.co/json/", headers={"User-Agent": "RONEX/" + APP_VERSION})
                with urllib.request.urlopen(req, timeout=10) as r:
                    j = json.loads(r.read().decode("utf-8"))
                loc = ", ".join(x for x in (j.get("city"), j.get("region"), j.get("country_name")) if x)
            except Exception:
                pass
            Clock.schedule_once(lambda *_: self.news_ai(loc, manual), 0)
        threading.Thread(target=locate, daemon=True).start()

    def news_ai(self, loc, manual):
        if not loc:
            self.news_busy = False
            if manual:
                self.notice("Local news", "Could not detect your location. Check your internet connection.")
            return
        prompt = (f"Use Google Search to find 3 recent, real news items (from the last few days if possible) that matter "
                  f"to someone doing marketing or running a small business in {loc}: local events, consumer trends, "
                  "advertising or social platform changes. For each give a headline, one sentence on why it matters for "
                  "marketing, and the source name and date. If you cannot find verified recent items, say so instead of "
                  "inventing any.")

        def done(ans, ok):
            self.news_busy = False
            if not ok:
                if manual:
                    self.notice("Local news", ans)
                return
            self.data["last_news"] = time.time()
            self.data["location"] = loc
            self.add_inbox(f"Local news - {loc}", ans)
            self.push_notification("Ronex AI local news", f"New marketing news for {loc}")
            if manual:
                self.show_inbox()
        self.call_ai(prompt, [], done, channel="insights", search=True, count=False)

    # --------------------------------------------------------------- home
    def tile(self, title, sub, color, cb, mark):
        t = Tile(bg=color, orientation="vertical", padding=dp(9), spacing=dp(2))
        t.add_widget(TLabel(text=f"[b]{mark}[/b]", markup=True, font_size=sp(20), size_hint_y=.3))
        t.add_widget(TLabel(text=f"[b]{title}[/b]", markup=True, font_size=sp(14), size_hint_y=.35))
        t.add_widget(TLabel(text=sub, font_size=sp(10), size_hint_y=.35, valign="top", color=(1, 1, 1, .88)))
        t.bind(on_release=lambda *_: cb())
        return t

    def tiles(self):
        return [
            self.tile("Create Campaign", "Build new marketing strategies", BLUE, lambda: self.go("campaigns"), "+"),
            self.tile("Generate Content", "Social posts, ads and blogs", GREEN, lambda: self.go("content"), "Aa"),
            self.tile("Analyze Performance", "Review data and insights", YELLOW, lambda: self.go("analytics"), "%"),
            self.tile("Manage Insights", "Teach the AI your preferences", RED, self.show_prefs, "AI"),
        ]

    def hello_card(self):
        c = Tile(bg="#16284A", padding=dp(14), orientation="vertical")
        c.add_widget(TLabel(text=f"[b]Hello, {self.settings.get('user_name') or 'there'}![/b]",
                            markup=True, font_size=sp(21)))
        c.bind(on_release=lambda *_: self.go("settings"))
        return c

    def profile_card(self):
        c = Tile(bg="#16284A", padding=dp(10), spacing=dp(4), orientation="vertical")
        top = BoxLayout(size_hint_y=.5, spacing=dp(10))
        av = Card(bg="#2D6BFF", radius=26, size_hint_x=None, width=dp(48), padding=dp(4))
        av.add_widget(TLabel(text="[b]AI[/b]", markup=True, halign="center", font_size=sp(15)))
        top.add_widget(av)
        top.add_widget(TLabel(text="[b]Personal\nMarketing AI[/b]", markup=True, font_size=sp(15)))
        c.add_widget(top)
        stats = BoxLayout(size_hint_y=.5)
        for val, lab in ((len(self.data["campaigns"]), "Active Campaigns"),
                         (self.data["sent"], "Engagements"), (self.replies_today(), "Replies Today")):
            col = BoxLayout(orientation="vertical")
            col.add_widget(TLabel(text=f"[b]{fmt_num(val)}[/b]", markup=True, halign="center", font_size=sp(17)))
            col.add_widget(TLabel(text=lab, halign="center", font_size=sp(9), color=rgba(MUTED)))
            stats.add_widget(col)
        c.add_widget(stats)
        c.bind(on_release=lambda *_: self.go("analytics"))
        return c

    def ask_bar(self):
        bar = Card(bg=PANEL, radius=14, padding=dp(6), spacing=dp(6))
        inp = TextInput(hint_text="Ask Ronex AI...", multiline=False, **self.ti_style((0, 0, 0, 0)))

        def ask(*_):
            t = inp.text.strip()
            self.open_chat(t or None, send=bool(t), channel="main")
        bar.add_widget(self.btn("Go", ask, bg=BLUE, fs=12, size_hint_x=None, width=dp(44)))
        inp.bind(on_text_validate=ask)
        bar.add_widget(inp)
        bar.add_widget(self.mic_for(inp))
        return bar

    def chip(self, text, prompt, **kw):
        t = Tile(bg="#16284A", padding=dp(10), **kw)
        t.add_widget(TLabel(text=f"[b]{text}[/b]  >", markup=True, font_size=sp(12)))
        t.bind(on_release=lambda *_: self.open_chat(prompt, send=True, channel="insights"))
        return t

    def build_home(self):
        wide = Window.width >= dp(600)
        sv = ScrollView(do_scroll_x=False, bar_width=0)
        page = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8), size_hint_y=None)
        sv.bind(height=lambda i, h: setattr(page, "height", max(h, dp(680))))
        sv.add_widget(page)
        self.body.add_widget(sv)

        hdr = BoxLayout(size_hint_y=.07, spacing=dp(8))
        dots = Tile(bg="#0F1B36", size_hint_x=None, width=dp(46))
        dots.add_widget(DotsIcon())
        dots.bind(on_release=lambda *_: self.show_history())
        bars = Tile(bg="#0F1B36", size_hint_x=None, width=dp(46))
        bars.add_widget(BarsIcon())
        bars.bind(on_release=lambda *_: self.show_menu())
        hdr.add_widget(dots)
        hdr.add_widget(Widget())
        hdr.add_widget(bars)
        page.add_widget(hdr)

        lg = BoxLayout(orientation="vertical", size_hint_y=.3 if wide else .24)
        lg.add_widget(self.logo(size_hint_y=.62))
        lg.add_widget(TLabel(text="[b]RONEX AI[/b]", markup=True, halign="center", color=rgba(CYAN),
                             font_size=sp(30), size_hint_y=.24))
        lg.add_widget(TLabel(text="- AI ASSISTANT -", halign="center", font_size=sp(11),
                             color=rgba(MUTED), size_hint_y=.14))
        page.add_widget(lg)

        t1, t2, t3, t4 = self.tiles()
        if wide:
            mid = BoxLayout(size_hint_y=.46, spacing=dp(8))
            left = BoxLayout(orientation="vertical", spacing=dp(8))
            left.add_widget(self.hello_card())
            row = BoxLayout(spacing=dp(8), size_hint_y=2)
            row.add_widget(t1)
            row.add_widget(t2)
            left.add_widget(row)
            left.add_widget(self.ask_bar())
            right = BoxLayout(orientation="vertical", spacing=dp(8))
            pc = self.profile_card()
            pc.size_hint_y = 1.3
            right.add_widget(pc)
            row2 = BoxLayout(spacing=dp(8), size_hint_y=1.7)
            row2.add_widget(t3)
            row2.add_widget(t4)
            right.add_widget(row2)
            mid.add_widget(left)
            mid.add_widget(right)
            page.add_widget(mid)
        else:
            hc = self.hello_card()
            hc.size_hint_y = .075
            page.add_widget(hc)
            pc = self.profile_card()
            pc.size_hint_y = .13
            page.add_widget(pc)
            grid = GridLayout(cols=2, spacing=dp(8), size_hint_y=.26)
            for t in (t1, t2, t3, t4):
                grid.add_widget(t)
            page.add_widget(grid)
            ab = self.ask_bar()
            ab.size_hint_y = .075
            page.add_widget(ab)

        page.add_widget(TLabel(text="[b]Recommended Insights[/b]", markup=True, font_size=sp(15), size_hint_y=.045))
        row = BoxLayout(spacing=dp(8), size_hint_y=.1 if not wide else .11)
        row.add_widget(self.chip("New Audience Segment Identified",
                                 "Help me identify a new audience segment for my marketing. Ask me about my current audience first.",
                                 size_hint_x=.36))
        row.add_widget(self.chip("Optimize Post Timing",
                                 "Advise me on the best times to post on social media. Ask which platforms and audience I have.",
                                 size_hint_x=.36))
        row.add_widget(Widget(size_hint_x=.04))
        fab = Tile(bg=CYAN, radius=26, size_hint_x=.24, padding=dp(6))
        fab.add_widget(TLabel(text="[b]+ Photo[/b]", markup=True, halign="center", color=rgba(BG), font_size=sp(14)))
        fab.bind(on_release=lambda *_: self.show_quick_add())
        row.add_widget(fab)
        page.add_widget(row)

    # ------------------------------------------------------------- popups
    def show_menu(self):
        n = self.unread()
        self.menu_popup("Menu", [
            (f"Inbox ({n} new)" if n else "Inbox", self.show_inbox),
            ("Open chat", lambda: self.open_chat(channel="main")),
            ("Chat history", self.show_history),
            ("Clear all chat history", self.clear_history),
            ("AI Settings", lambda: self.go("settings")),
        ])

    def show_quick_add(self):
        self.menu_popup("Quick add", [
            ("New chat", self.new_chat),
            ("Analyze a photo or video", lambda: self.pick_photo(lambda: self.open_chat(channel=self.channel))),
            ("New campaign", lambda: self.go("campaigns")),
            ("Generate content", lambda: self.go("content")),
        ])

    def clear_history(self):
        self.data["convs"] = []
        self.cur = {}
        self.save_data()
        self.notice("History cleared", "All chats were deleted from this account.")

    def new_chat(self):
        self.new_conv(self.channel)
        self.go("chat")

    def show_history(self):
        box = BoxLayout(orientation="vertical", spacing=dp(6), padding=dp(10))
        pop = Popup(title="Chat history", content=box, size_hint=(.9, .8), background_color=rgba(PANEL))
        sv = ScrollView(do_scroll_x=False)
        grid = GridLayout(cols=1, size_hint_y=None, spacing=dp(6))
        grid.bind(minimum_height=grid.setter("height"))
        convs = self.data["convs"]
        if not convs:
            grid.add_widget(AutoLabel(text="No chats yet.", color=rgba(MUTED)))
        for i in reversed(range(len(convs))):
            ch = CHANNELS.get(convs[i].get("channel", "main"), CHANNELS["main"])
            b = self.btn(f"{ch['title']}: {convs[i]['title'][:34]}", None, bg=PANEL2, size_hint_y=None, height=dp(46), fs=13)
            b.lbl.color = rgba(ch["color"])
            b.bind(on_release=lambda _i, i=i: (pop.dismiss(), self.open_conv(i)))
            grid.add_widget(b)
        sv.add_widget(grid)
        box.add_widget(sv)
        row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        row.add_widget(self.btn("+ New chat", lambda *_: (pop.dismiss(), self.new_chat()), bg=CYAN, fg=BG))
        row.add_widget(self.btn("Close", pop.dismiss))
        box.add_widget(row)
        pop.open()

    def open_conv(self, i):
        self.channel = self.data["convs"][i].get("channel", "main")
        self.cur[self.channel] = i
        self.go("chat")

    def show_prefs(self):
        box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(10))
        pop = Popup(title="Manage Insights - teach the AI", content=box, size_hint=(.92, .85),
                    background_color=rgba(PANEL))
        box.add_widget(TLabel(text="Add things Ronex AI should always remember (tone, brand, audience...).",
                              font_size=sp(12), color=rgba(MUTED), size_hint_y=None, height=dp(40)))
        sv = ScrollView(do_scroll_x=False)
        grid = GridLayout(cols=1, size_hint_y=None, spacing=dp(6))
        grid.bind(minimum_height=grid.setter("height"))
        sv.add_widget(grid)
        box.add_widget(sv)
        inp = TextInput(hint_text="e.g. Our brand voice is playful and short", multiline=False, **self.ti_style())
        box.add_widget(self.with_mic(inp, size_hint_y=None, height=dp(44)))

        def render():
            grid.clear_widgets()
            prefs = self.settings["prefs"]
            if not prefs:
                grid.add_widget(AutoLabel(text="Nothing saved yet.", color=rgba(MUTED)))
            for i, text in enumerate(prefs):
                r = Card(bg=PANEL2, size_hint_y=None, height=dp(52), padding=dp(6), spacing=dp(6))
                r.add_widget(TLabel(text=text, font_size=sp(12)))
                r.add_widget(self.btn("Del", lambda *_, i=i: remove(i), bg=RED, fs=11, size_hint_x=None, width=dp(48)))
                grid.add_widget(r)

        def remove(i):
            self.settings["prefs"].pop(i)
            self.save_data()
            render()

        def add(*_):
            t = inp.text.strip()
            if t:
                self.settings["prefs"].append(t)
                self.save_data()
                inp.text = ""
                render()
        inp.bind(on_text_validate=add)
        row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        row.add_widget(self.btn("Add", add, bg=CYAN, fg=BG))
        row.add_widget(self.btn("Close", pop.dismiss))
        box.add_widget(row)
        render()
        pop.open()

    # -------------------------------------------------------- photo/video
    def pick_photo(self, then):
        if not self.settings.get("media_ok"):
            self.menu_popup("Photos & videos not allowed",
                            [("Open AI Settings to allow it", lambda: self.go("settings"))])
            return
        start = "/storage/emulated/0" if os.path.exists("/storage/emulated/0") else os.path.expanduser("~")
        fc = FileChooserListView(path=start, filters=["*.jpg", "*.jpeg", "*.png", "*.webp", "*.mp4", "*.mov",
                                                      "*.webm", "*.3gp"])
        box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        box.add_widget(fc)
        row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        pop = Popup(title="Choose a photo or video", content=box, size_hint=(.95, .9), background_color=rgba(PANEL))

        def choose(*_):
            if fc.selection:
                self.pending_image = fc.selection[0]
                pop.dismiss()
                then()
        row.add_widget(self.btn("Attach", choose, bg=CYAN, fg=BG))
        row.add_widget(self.btn("Cancel", pop.dismiss))
        box.add_widget(row)
        pop.open()

    # ------------------------------------------------------- conversations
    def conv(self, channel):
        idx = self.cur.get(channel)
        convs = self.data["convs"]
        if idx is None or idx >= len(convs) or convs[idx].get("channel") != channel:
            for i in reversed(range(len(convs))):
                if convs[i].get("channel") == channel:
                    self.cur[channel] = i
                    return convs[i]
            return self.new_conv(channel)
        return convs[idx]

    def new_conv(self, channel):
        self.data["convs"].append({"title": "New chat", "channel": channel, "messages": []})
        self.cur[channel] = len(self.data["convs"]) - 1
        self.save_data()
        return self.data["convs"][-1]

    def bump_reply(self):
        today = str(datetime.date.today())
        if self.data.get("day") != today:
            self.data["day"], self.data["today"] = today, 0
        self.data["today"] += 1
        self.save_data()

    def replies_today(self):
        return self.data["today"] if self.data.get("day") == str(datetime.date.today()) else 0

    # --------------------------------------------------------------- chat
    def open_chat(self, prompt=None, send=False, channel=None):
        if channel:
            self.channel = channel
        self.go("chat")
        if prompt:
            self.input_box.text = prompt
            if send:
                Clock.schedule_once(self.send_chat, .15)

    def build_chat(self):
        ch = CHANNELS[self.channel]
        p = self.page((10, 8))
        hdr = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(6))
        hdr.add_widget(self.btn("<", lambda *_: self.go("home"), fs=18, size_hint=(None, 1), width=dp(44)))
        col = BoxLayout(orientation="vertical")
        name = self.settings.get("assistant_name", "Ronex AI") if self.channel == "main" else ch["title"]
        col.add_widget(TLabel(text=f"[b]{name}[/b]", markup=True, font_size=sp(18), color=rgba(ch["color"])))
        self.status_label = TLabel(text=ch["sub"], font_size=sp(12), color=rgba(MUTED))
        col.add_widget(self.status_label)
        hdr.add_widget(col)
        hdr.add_widget(self.btn("History", lambda *_: self.show_history(), fs=12, size_hint=(None, 1), width=dp(66)))
        hdr.add_widget(self.btn("New", lambda *_: self.new_chat(), fs=12, size_hint=(None, 1), width=dp(50)))
        p.add_widget(hdr)

        self.chat_scroll = ScrollView(do_scroll_x=False, bar_width=dp(3))
        self.chat_stack = GridLayout(cols=1, size_hint_y=None, spacing=dp(10), padding=(dp(2), dp(8)))
        self.chat_stack.bind(minimum_height=self.chat_stack.setter("height"))
        self.chat_scroll.add_widget(self.chat_stack)
        p.add_widget(self.chat_scroll)

        comp = BoxLayout(size_hint_y=None, height=dp(56), spacing=dp(6))
        comp.add_widget(self.btn("+", lambda *_: self.pick_photo(self.refresh_attach), fs=20, fg=CYAN,
                                 size_hint=(None, 1), width=dp(44)))
        self.input_box = TextInput(hint_text=f"Message {name}...", multiline=True, **self.ti_style())
        self.input_box.bind(focus=lambda _i, f: f and self.scroll_bottom())
        comp.add_widget(self.input_box)
        comp.add_widget(self.mic_for(self.input_box))
        comp.add_widget(self.btn("Send", self.send_chat, bg=ch["color"], fg=BG, fs=13, size_hint=(None, 1), width=dp(54)))
        p.add_widget(comp)

        msgs = self.conv(self.channel)["messages"]
        if not msgs:
            self.add_bubble("assistant", ch["greeting"], copy=False)
            for s in ch["starters"]:
                t = Tile(bg=PANEL2, size_hint_y=None, height=dp(44), padding=dp(10))
                t.add_widget(TLabel(text=s, font_size=sp(13), color=rgba(ch["color"])))
                t.bind(on_release=lambda _i, s=s: (setattr(self.input_box, "text", s), self.send_chat()))
                self.chat_stack.add_widget(t)
        for m in msgs:
            self.add_bubble(m.get("role", "assistant"), m.get("text", ""))
        self.refresh_attach()

    def refresh_attach(self):
        if self.screen != "chat":
            self.go("chat")
            return
        if self.pending_image:
            self.status_label.text = "Attached: " + os.path.basename(self.pending_image)[:26]
        else:
            self.status_label.text = CHANNELS[self.channel]["sub"]

    def scroll_bottom(self):
        Clock.schedule_once(lambda *_: self.screen == "chat" and setattr(self.chat_scroll, "scroll_y", 0), .15)

    def add_bubble(self, role, text, copy=True):
        ch = CHANNELS[self.channel]
        user = role == "user"
        row = BoxLayout(size_hint_y=None)
        bub = Card(bg=USER_BUBBLE if user else ch["bubble"], orientation="vertical", size_hint=(.86, None),
                   padding=dp(10), spacing=dp(4))
        bub.bind(minimum_height=bub.setter("height"))
        bub.bind(height=lambda i, h: setattr(row, "height", h))
        who = "You" if user else (self.settings.get("assistant_name", "Ronex AI") if self.channel == "main" else ch["title"])
        bub.add_widget(AutoLabel(text=f"[b]{who}[/b]", markup=True, font_size=sp(12),
                                 color=rgba(WHITE if user else ch["color"])))
        bub.add_widget(AutoLabel(text=str(text), font_size=sp(15)))
        if not user and copy:
            bub.add_widget(self.btn("Copy", lambda *_: Clipboard.copy(str(text)), fs=11, bg=PANEL2,
                                    size_hint=(None, None), width=dp(56), height=dp(26)))
        if user:
            row.add_widget(Widget(size_hint_x=.14))
        row.add_widget(bub)
        if not user:
            row.add_widget(Widget(size_hint_x=.14))
        self.chat_stack.add_widget(row)
        self.scroll_bottom()
        return row

    def send_chat(self, *_):
        if self.screen != "chat":
            return
        if self.busy:
            self.notice("Please wait", "The AI is still answering.")
            return
        text = self.input_box.text.strip()
        if not text and not self.pending_image:
            return
        text = text or "Describe and analyze this file."
        self.input_box.text = ""
        channel = self.channel
        c = self.conv(channel)
        if not c["messages"]:
            c["title"] = text[:40]
        c["messages"].append({"role": "user", "text": text})
        self.data["sent"] += 1
        self.save_data()
        self.add_bubble("user", text)
        history = c["messages"][:-1][-24:]
        img, self.pending_image = self.pending_image, None
        self.busy = True
        self.status_label.text = "typing..."
        self.typing = self.add_bubble("assistant", "typing...", copy=False)
        self.call_ai(text, history, lambda ans, ok: self.on_chat_reply(c, channel, ans, ok), image=img, channel=channel)

    def on_chat_reply(self, c, channel, answer, ok):
        self.busy = False
        if ok:
            c["messages"].append({"role": "assistant", "text": answer})
            self.save_data()
        if self.screen == "chat" and self.channel == channel and self.cur.get(channel) is not None \
                and self.data["convs"][self.cur[channel]] is c:
            try:
                self.chat_stack.remove_widget(self.typing)
            except Exception:
                pass
            self.add_bubble("assistant", answer)
            self.refresh_attach()

    # ------------------------------------------------------------- AI call
    def system_text(self, channel):
        s = str(self.settings.get("instructions") or DEFAULT_INSTRUCTIONS)
        s += "\n\n" + CHANNELS[channel]["persona"]
        s += f"\nThe user's name is {self.settings.get('user_name') or 'unknown'}."
        prefs = self.settings.get("prefs") or []
        if prefs:
            s += "\n\nSaved user preferences (always follow them):\n" + "\n".join("- " + p for p in prefs)
        return s

    def call_ai(self, prompt, history, done, image=None, channel="main", search=False, count=True):
        key = get_api_key(self.user_data_dir)
        if not key:
            Clock.schedule_once(lambda *_: done("The Gemini API key was not found. Set GEMINI_API_KEY or create "
                                                "gemini_key.txt next to the app (see the top of the code).", False), 0)
            return
        model = str(self.settings.get("model") or DEFAULT_MODEL).strip()
        system = self.system_text(channel)
        try:
            temp = float(self.settings.get("temperature", 0.7))
        except Exception:
            temp = 0.7

        def work():
            ok, answer = True, ""
            try:
                contents = []
                for m in history:
                    txt = m.get("text", "")
                    role = "user" if m.get("role") == "user" else "model"
                    if not txt or (not contents and role == "model"):
                        continue
                    contents.append({"role": role, "parts": [{"text": str(txt)}]})
                parts = [{"text": prompt}]
                if image:
                    with open(image, "rb") as f:
                        raw = f.read()
                    mime = mimetypes.guess_type(image)[0] or "image/jpeg"
                    limit = 12000000 if mime.startswith("video") else 6000000
                    if len(raw) > limit:
                        raise ValueError(f"File is too large (max about {limit // 1000000} MB).")
                    parts.append({"inlineData": {"mimeType": mime, "data": base64.b64encode(raw).decode()}})
                contents.append({"role": "user", "parts": parts})
                payload = {"systemInstruction": {"parts": [{"text": system}]}, "contents": contents,
                           "generationConfig": {"temperature": temp, "maxOutputTokens": 1500}}
                if search:
                    payload["tools"] = [{"google_search": {}}]
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
                req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST",
                                             headers={"Content-Type": "application/json", "x-goog-api-key": key})
                with urllib.request.urlopen(req, timeout=90) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
                cands = result.get("candidates", [])
                if cands:
                    answer = "".join(p.get("text", "") for p in cands[0].get("content", {}).get("parts", []))
                if not answer:
                    ok, answer = False, "The AI returned an empty response. Try again."
            except urllib.error.HTTPError as exc:
                ok = False
                try:
                    details = exc.read().decode("utf-8")[:500]
                except Exception:
                    details = str(exc)
                answer = f"Gemini API error ({exc.code}). Check the API key, model name or quota.\n{details}"
            except Exception as exc:
                ok, answer = False, f"Could not complete the request.\n{exc}"

            def finish(*_):
                if ok and count and self.acct_id:
                    self.bump_reply()
                done(answer, ok)
            Clock.schedule_once(finish, 0)
        threading.Thread(target=work, daemon=True).start()

    # --------------------------------------------------- reusable AI tool
    def ai_tool(self, page, hint, button, make_prompt, input_size=.25, channel="main"):
        box = TextInput(hint_text=hint, multiline=True, **self.ti_style())
        page.add_widget(self.with_mic(box, size_hint_y=input_size))
        wrap = Card(bg=PANEL, padding=dp(10))
        sv = ScrollView(do_scroll_x=False)
        result = AutoLabel(text="Your result will appear here.", color=rgba(MUTED), font_size=sp(14))
        sv.add_widget(result)
        wrap.add_widget(sv)
        page.add_widget(wrap)

        def run(*_):
            if self.busy:
                self.notice("Please wait", "The AI is still working on another request.")
                return
            prompt = make_prompt(box.text.strip())
            if not prompt:
                self.notice("Nothing to do", "Type or paste something first.")
                return
            self.busy = True
            result.text, result.color = "Working...", rgba(MUTED)

            def done(ans, ok):
                self.busy = False
                result.text, result.color = ans, rgba(WHITE if ok else "#FF9A9A")
            self.call_ai(prompt, [], done, channel=channel)
        row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        row.add_widget(self.btn(button, run, bg=CHANNELS[channel]["color"], fg=BG))
        row.add_widget(self.btn("Copy", lambda *_: Clipboard.copy(result.text), size_hint_x=.5))
        row.add_widget(self.btn("To chat", lambda *_: self.open_chat(box.text.strip() or None, channel=channel),
                                size_hint_x=.6))
        page.add_widget(row)

    # ---------------------------------------------------------- campaigns
    def build_campaigns(self):
        p = self.page()
        p.add_widget(self.header("Campaigns", chat="campaign"))
        ti = self.ti_style()
        form = Card(bg=PANEL, orientation="vertical", size_hint_y=None, height=dp(170), padding=dp(10), spacing=dp(6))
        name = TextInput(hint_text="Campaign name", multiline=False, **ti)
        goal = TextInput(hint_text="Goal / audience (optional)", multiline=False, **ti)
        form.add_widget(self.with_mic(name, size_hint_y=None, height=dp(44)))
        form.add_widget(self.with_mic(goal, size_hint_y=None, height=dp(44)))

        def add(*_):
            if not name.text.strip():
                self.notice("Name needed", "Give the campaign a name.")
                return
            self.data["campaigns"].append({"name": name.text.strip(), "goal": goal.text.strip()})
            self.save_data()
            name.text = goal.text = ""
            render()
        form.add_widget(self.btn("Create campaign", add, bg=BLUE, size_hint_y=None, height=dp(44)))
        p.add_widget(form)
        sv = ScrollView(do_scroll_x=False)
        grid = GridLayout(cols=1, size_hint_y=None, spacing=dp(8))
        grid.bind(minimum_height=grid.setter("height"))
        sv.add_widget(grid)
        p.add_widget(sv)

        def delete(i):
            self.data["campaigns"].pop(i)
            self.save_data()
            render()

        def render():
            grid.clear_widgets()
            camps = self.data["campaigns"]
            if not camps:
                grid.add_widget(AutoLabel(text="No campaigns yet. Create your first one above.", color=rgba(MUTED)))
            for i, c in enumerate(camps):
                r = Card(bg=PANEL2, size_hint_y=None, height=dp(78), padding=dp(8), spacing=dp(6))
                info = BoxLayout(orientation="vertical")
                info.add_widget(TLabel(text=f"[b]{c['name']}[/b]", markup=True, font_size=sp(15)))
                info.add_widget(TLabel(text=c.get("goal") or "No goal set", font_size=sp(11), color=rgba(MUTED)))
                r.add_widget(info)
                prompt = (f"Create a detailed marketing campaign plan for '{c['name']}'. "
                          f"Goal/audience: {c.get('goal') or 'not specified'}. "
                          "Include audience, channels, a 2-week schedule and metrics to track.")
                r.add_widget(self.btn("Plan", lambda *_, pr=prompt: self.open_chat(pr, send=True, channel="campaign"),
                                      bg=BLUE, fs=12, size_hint_x=None, width=dp(56)))
                r.add_widget(self.btn("Del", lambda *_, i=i: delete(i), bg=RED, fs=12, size_hint_x=None, width=dp(50)))
                grid.add_widget(r)
        render()

    # ------------------------------------------------------------ content
    def build_content(self):
        p = self.page()
        p.add_widget(self.header("Generate Content", chat="content"))
        row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        btns = []

        def pick(i):
            self.ctype = i
            for j, b in enumerate(btns):
                b.lbl.color = rgba(BG if j == i else WHITE)
                b.set_bg(GREEN if j == i else PANEL2)
        for i, (label, _) in enumerate(CONTENT_TYPES):
            b = self.btn(label, None, fs=12)
            b.bind(on_release=lambda _i, i=i: pick(i))
            btns.append(b)
            row.add_widget(b)
        p.add_widget(row)
        pick(self.ctype)
        self.ai_tool(p, "What is it about? e.g. launch of our new coffee brand", "Generate",
                     lambda t: (CONTENT_TYPES[self.ctype][1] + t) if t else None, .2, channel="content")

    # ---------------------------------------------------------- analytics
    def build_analytics(self):
        p = self.page()
        p.add_widget(self.header("Analyze Performance", chat="analytics"))
        grid = GridLayout(cols=4, size_hint_y=None, height=dp(66), spacing=dp(6))
        for val, lab in ((len(self.data["campaigns"]), "Campaigns"), (self.data["sent"], "Messages"),
                         (self.replies_today(), "Replies today"), (len(self.data["convs"]), "Chats")):
            c = Card(bg=PANEL, orientation="vertical", padding=dp(4))
            c.add_widget(TLabel(text=f"[b]{fmt_num(val)}[/b]", markup=True, halign="center", font_size=sp(18)))
            c.add_widget(TLabel(text=lab, halign="center", font_size=sp(9), color=rgba(MUTED)))
            grid.add_widget(c)
        p.add_widget(grid)
        self.ai_tool(p, "Paste your campaign metrics or report here...", "Analyze",
                     lambda t: ("Analyze this marketing performance data. Give key findings, problems and "
                                "3 concrete next actions:\n\n" + t) if t else None, .3, channel="analytics")

    # ----------------------------------------------------------- settings
    def onoff_row(self, g, label, getter, tap):
        row = Card(bg=PANEL, size_hint_y=None, height=dp(50), padding=dp(8), spacing=dp(8))
        row.add_widget(TLabel(text=label, font_size=sp(13)))
        b = self.btn("", None, fs=12, size_hint_x=None, width=dp(60))

        def refresh(*_):
            on = bool(getter())
            b.lbl.text = "ON" if on else "OFF"
            b.set_bg(GREEN if on else PANEL2)
        b.bind(on_release=lambda *_: tap(refresh))
        refresh()
        row.add_widget(b)
        g.add_widget(row)

    def build_settings(self):
        p = self.page()
        p.add_widget(self.header("AI Settings"))
        sv = ScrollView(do_scroll_x=False)
        g = GridLayout(cols=1, size_hint_y=None, spacing=dp(6), padding=(0, 0, 0, dp(12)))
        g.bind(minimum_height=g.setter("height"))
        s = self.settings
        ti = self.ti_style()

        def section(t):
            g.add_widget(TLabel(text=f"[b]{t}[/b]", markup=True, color=rgba(CYAN), font_size=sp(14),
                                size_hint_y=None, height=dp(34)))

        def action(text, cb, bg=PANEL2):
            g.add_widget(self.btn(text, lambda *_: cb(), bg=bg, size_hint_y=None, height=dp(44)))

        section("Account")
        g.add_widget(AutoLabel(text="Signed in as: " + (self.acct or {}).get("ident", ""), font_size=sp(13),
                               color=rgba(MUTED)))
        action("Log out", lambda: self.logout("login"))
        action("Add / switch account", lambda: self.logout("signup"))
        action("Delete account", self.confirm_delete, RED)

        section("Permissions")

        def perm_tap(kind):
            def tap(refresh):
                if self.settings.get(kind + "_ok"):
                    self.settings[kind + "_ok"] = False
                    self.save_data()
                    refresh()
                    self.notice("Permission off", "Turned off inside Ronex AI. To fully revoke it, also remove it in "
                                                  "your phone's app settings.")
                else:
                    self.ensure_perm(kind, after=refresh)
            return tap
        self.onoff_row(g, "Photos & videos", lambda: s.get("media_ok"), perm_tap("media"))
        self.onoff_row(g, "Microphone (voice typing)", lambda: s.get("mic_ok"), perm_tap("mic"))

        section("Notifications")

        def notify_tap(refresh):
            s["notify"] = not s.get("notify")
            self.save_data()
            if s["notify"]:
                self.ensure_perm("notify")
            refresh()

        def news_tap(refresh):
            s["news"] = not s.get("news")
            self.save_data()
            refresh()
        self.onoff_row(g, "Update & news notifications", lambda: s.get("notify"), notify_tap)
        self.onoff_row(g, "Local news by my location", lambda: s.get("news"), news_tap)
        n = self.unread()
        action(f"Open inbox ({n} new)" if n else "Open inbox", self.show_inbox)
        action("Get local news now", lambda: self.refresh_news(True))
        action("Check for updates", lambda: self.check_updates(True))

        section("AI")

        def field(label, value, h=44, **kw):
            g.add_widget(AutoLabel(text=label, color=rgba(MUTED), font_size=sp(12)))
            w = TextInput(text=str(value), multiline=kw.pop("multiline", False), size_hint_y=None,
                          height=dp(h), **ti, **kw)
            g.add_widget(w)
            return w
        user = field("Your name", s.get("user_name", ""))
        name = field("Assistant display name", s.get("assistant_name", "Ronex AI"))
        model = field("Gemini model name", s.get("model", DEFAULT_MODEL))
        instr = field("System instructions (main way to change AI behaviour)",
                      s.get("instructions", DEFAULT_INSTRUCTIONS), h=150, multiline=True)
        temp = field("Temperature 0-1 (lower = steadier, higher = more varied)",
                     s.get("temperature", 0.7), input_filter="float")

        def save(*_):
            s["user_name"] = user.text.strip() or "there"
            s["assistant_name"] = name.text.strip() or "Ronex AI"
            s["model"] = model.text.strip() or DEFAULT_MODEL
            s["instructions"] = instr.text.strip() or DEFAULT_INSTRUCTIONS
            try:
                s["temperature"] = max(0.0, min(1.0, float(temp.text or "0.7")))
            except ValueError:
                s["temperature"] = 0.7
            self.save_data()
            self.notice("Saved", "Your settings were saved (encrypted) on this device.")
        g.add_widget(self.btn("Save settings", save, bg=CYAN, fg=BG, size_hint_y=None, height=dp(48)))
        action("Reset instructions", lambda: setattr(instr, "text", DEFAULT_INSTRUCTIONS))
        action("Teach the AI (preferences)", self.show_prefs, RED)
        action("Clear chat history", self.clear_history)
        g.add_widget(AutoLabel(text=f"Ronex AI v{APP_VERSION}", color=rgba(MUTED), font_size=sp(11), halign="center"))
        sv.add_widget(g)
        p.add_widget(sv)


if __name__ == "__main__":
    RonexAIApp().run()
