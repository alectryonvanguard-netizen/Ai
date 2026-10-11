"""
QYRONEX AI - Kivy app (Pydroid 3)
Dashboard matches the mockup. Every button has its own job.
Optional: put a logo image named qyronex_logo.png next to this file.
For a public release, move the API key to a secure backend.
"""
import base64
import datetime
import json
import mimetypes
import os
import threading
import urllib.error
import urllib.request

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

APP_NAME = "QYRONEX AI"
DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_INSTRUCTIONS = (
    "You are QYRONEX, a helpful, friendly, honest personal marketing AI assistant inside the "
    "QYRONEX AI app. Answer clearly, adapt to the user's preferred style, ask a question when a "
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
AI_BUBBLE = "#162447"
BLUE, GREEN, YELLOW, RED = "#2D6BFF", "#1FAE62", "#F2B705", "#E04848"

NAV = [("home", "Home"), ("campaigns", "Campaigns"), ("content", "Content"),
       ("analytics", "Analytics"), ("settings", "AI Settings")]
CONTENT_TYPES = [
    ("Social posts", "Write 3 social media posts (with hashtags and a call to action) about: "),
    ("Ad copy", "Write 3 ad copy variations (headline + body + call to action) for: "),
    ("Blog ideas", "Give 5 blog title ideas and a detailed outline for the best one about: "),
]


def rgba(h):
    return get_color_from_hex(h)


def fmt_num(n):
    return f"{n/1000:.1f}K" if n >= 1000 else str(n)


# ----------------------------------------------------------------- widgets
class Card(BoxLayout):
    """Rounded coloured panel."""
    def __init__(self, bg=PANEL, radius=14, **kw):
        super().__init__(**kw)
        with self.canvas.before:
            Color(*rgba(bg))
            self._rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(radius)])
        self.bind(pos=self._upd, size=self._upd)

    def _upd(self, *_):
        self._rect.pos = self.pos
        self._rect.size = self.size


class Tile(ButtonBehavior, Card):
    """Tappable rounded panel."""


class TLabel(Label):
    """Label that wraps inside its own box."""
    def __init__(self, **kw):
        kw.setdefault("halign", "left")
        kw.setdefault("valign", "middle")
        kw.setdefault("color", rgba(WHITE))
        super().__init__(**kw)
        self.bind(size=lambda i, v: setattr(i, "text_size", (v[0], v[1])))


class AutoLabel(Label):
    """Wrapping label whose height follows its text (for scroll areas)."""
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
    """Animated glowing ring logo (used when no logo image is supplied)."""
    angle = NumericProperty(0)

    def __init__(self, **kw):
        super().__init__(**kw)
        self.lbl = Label(text="[b]Q[/b]", markup=True, color=rgba(CYAN))
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


# -------------------------------------------------------------------- app
class QYRONEXAIApp(App):
    def build(self):
        self.title = APP_NAME
        Window.clearcolor = rgba(BG)
        try:
            Window.softinput_mode = "pan"
        except Exception:
            pass
        self.settings_path = os.path.join(self.user_data_dir, "qyronex_settings.json")
        self.data_path = os.path.join(self.user_data_dir, "qyronex_data.json")
        self.settings = {"api_key": "", "model": DEFAULT_MODEL, "instructions": DEFAULT_INSTRUCTIONS,
                         "assistant_name": "QYRONEX", "user_name": "Alex", "temperature": 0.7, "prefs": []}
        self.data = {"campaigns": [], "convs": [], "sent": 0, "day": "", "today": 0}
        self.cur = None
        self.busy = False
        self.pending_image = None
        self.ctype = 0
        self.screen = "boot"
        self.load_local()
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
        Clock.schedule_once(lambda *_: self.go("home"), 3)
        return root

    # ------------------------------------------------------------ storage
    def load_local(self):
        for path, target in ((self.settings_path, self.settings), (self.data_path, self.data)):
            try:
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as f:
                        saved = json.load(f)
                    target.update({k: v for k, v in saved.items() if k in target})
            except Exception:
                pass
        if self.data["convs"]:
            self.cur = len(self.data["convs"]) - 1

    def save_settings(self):
        try:
            os.makedirs(self.user_data_dir, exist_ok=True)
            with open(self.settings_path, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            self.notice("Could not save settings", str(exc))

    def save_data(self):
        try:
            os.makedirs(self.user_data_dir, exist_ok=True)
            self.data["convs"] = self.data["convs"][-40:]
            for c in self.data["convs"]:
                c["messages"] = c["messages"][-120:]
            with open(self.data_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False)
        except Exception:
            pass

    def on_stop(self):
        self.save_data()
        self.save_settings()

    # ------------------------------------------------------ conversations
    def conv(self):
        if self.cur is None or self.cur >= len(self.data["convs"]):
            self.new_conv()
        return self.data["convs"][self.cur]

    def new_conv(self):
        self.data["convs"].append({"title": "New chat", "messages": []})
        self.cur = len(self.data["convs"]) - 1
        self.save_data()

    def bump_reply(self):
        today = str(datetime.date.today())
        if self.data.get("day") != today:
            self.data["day"], self.data["today"] = today, 0
        self.data["today"] += 1
        self.save_data()

    def replies_today(self):
        return self.data["today"] if self.data.get("day") == str(datetime.date.today()) else 0

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

    def page(self, pad=(12, 8)):
        p = BoxLayout(orientation="vertical", padding=(dp(pad[0]), dp(pad[1])), spacing=dp(8))
        self.body.add_widget(p)
        return p

    def header(self, title):
        row = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(8))
        row.add_widget(self.btn("<", lambda *_: self.go("home"), fs=18, size_hint=(None, 1), width=dp(46)))
        row.add_widget(TLabel(text=f"[b]{title}[/b]", markup=True, font_size=sp(20)))
        return row

    def logo(self, **kw):
        try:
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qyronex_logo.png")
        except Exception:
            path = ""
        if path and os.path.exists(path):
            return Image(source=path, allow_stretch=True, keep_ratio=True, **kw)
        return LogoMark(**kw)

    def go(self, name):
        self.screen = name
        self.body.clear_widgets()
        self.nav.height = dp(54)
        self.nav.opacity = 1
        getattr(self, "build_" + name)()
        for k, t in self.nav_tiles.items():
            on = k == name
            t.lbl.color = rgba(CYAN if on else MUTED)
            t._c_on = on
        Window.release_all_keyboards()

    def notice(self, title, message):
        box = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(12))
        box.add_widget(TLabel(text=message, halign="center", font_size=sp(14)))
        ok = self.btn("OK", None, bg=CYAN, fg=BG, size_hint_y=None, height=dp(44))
        box.add_widget(ok)
        pop = Popup(title=title, content=box, size_hint=(.88, .4), background_color=rgba(PANEL))
        ok.bind(on_release=pop.dismiss)
        pop.open()

    def menu_popup(self, title, items, size=(.86, None)):
        box = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        pop = Popup(title=title, content=box, size_hint=(size[0], None),
                    height=dp(110 + 54 * len(items)), background_color=rgba(PANEL))
        for label, cb in items:
            b = self.btn(label, None, size_hint_y=None, height=dp(46))
            b.bind(on_release=lambda _i, cb=cb: (pop.dismiss(), cb()))
            box.add_widget(b)
        c = self.btn("Close", pop.dismiss, bg=PANEL, fg=MUTED, size_hint_y=None, height=dp(40))
        box.add_widget(c)
        pop.open()

    # --------------------------------------------------------------- boot
    def build_boot(self):
        self.body.clear_widgets()
        p = BoxLayout(orientation="vertical", padding=dp(20), spacing=dp(10))
        p.add_widget(Widget())
        p.add_widget(self.logo(size_hint_y=None, height=min(Window.width * .7, dp(280))))
        p.add_widget(TLabel(text="[b]QYRONEX[/b]", markup=True, halign="center", color=rgba(CYAN),
                            font_size=sp(34), size_hint_y=None, height=dp(50)))
        p.add_widget(TLabel(text="AI ASSISTANT  -  INITIALIZING", halign="center", color=rgba(MUTED),
                            font_size=sp(12), size_hint_y=None, height=dp(24)))
        p.add_widget(Widget())
        self.body.add_widget(p)

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
        inp = TextInput(hint_text="Ask QYRONEX...", multiline=False, **self.ti_style((0, 0, 0, 0)))

        def ask(*_):
            self.open_chat(inp.text.strip() or None, send=bool(inp.text.strip()))
        go = self.btn("Go", ask, bg=BLUE, fs=12, size_hint_x=None, width=dp(44))
        inp.bind(on_text_validate=ask)
        mic = self.btn("Mic", lambda *_: self.start_voice(inp), bg="#0F1B36", fg=CYAN, fs=12,
                       size_hint_x=None, width=dp(44))
        bar.add_widget(go)
        bar.add_widget(inp)
        bar.add_widget(mic)
        return bar

    def chip(self, text, prompt, **kw):
        t = Tile(bg="#16284A", padding=dp(10), **kw)
        t.add_widget(TLabel(text=f"[b]{text}[/b]  >", markup=True, font_size=sp(12)))
        t.bind(on_release=lambda *_: self.open_chat(prompt, send=True))
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
        lg.add_widget(TLabel(text="[b]QYRONEX[/b]", markup=True, halign="center", color=rgba(CYAN),
                             font_size=sp(30), size_hint_y=.24))
        lg.add_widget(TLabel(text="- AI ASSISTANT -", halign="center", font_size=sp(11),
                             color=rgba(MUTED), size_hint_y=.14))
        page.add_widget(lg)

        t1, t2, t3, t4 = self.tiles()
        if wide:  # tablet layout, like the mockup
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
        else:  # phone layout
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

        page.add_widget(TLabel(text="[b]Recommended Insights[/b]", markup=True, font_size=sp(15),
                               size_hint_y=.045))
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
        self.menu_popup("Menu", [
            ("Open chat", lambda: self.go("chat")),
            ("Chat history", self.show_history),
            ("Clear all chat history", self.clear_history),
            ("AI Settings", lambda: self.go("settings")),
        ])

    def show_quick_add(self):
        self.menu_popup("Quick add", [
            ("New chat", self.new_chat),
            ("Analyze a photo with AI", lambda: self.pick_photo(lambda: self.go("chat"))),
            ("New campaign", lambda: self.go("campaigns")),
            ("Generate content", lambda: self.go("content")),
        ])

    def clear_history(self):
        self.data["convs"] = []
        self.cur = None
        self.save_data()
        self.notice("History cleared", "All chats were deleted from this device.")

    def new_chat(self):
        self.new_conv()
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
            b = self.btn(convs[i]["title"][:40] or "Chat", None, size_hint_y=None, height=dp(46))
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
        self.cur = i
        self.go("chat")

    def show_prefs(self):
        box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(10))
        pop = Popup(title="Manage Insights - teach the AI", content=box, size_hint=(.92, .85),
                    background_color=rgba(PANEL))
        box.add_widget(TLabel(text="Add things QYRONEX should always remember (tone, brand, audience...).",
                              font_size=sp(12), color=rgba(MUTED), size_hint_y=None, height=dp(40)))
        sv = ScrollView(do_scroll_x=False)
        grid = GridLayout(cols=1, size_hint_y=None, spacing=dp(6))
        grid.bind(minimum_height=grid.setter("height"))
        sv.add_widget(grid)
        box.add_widget(sv)
        inp = TextInput(hint_text="e.g. Our brand voice is playful and short", multiline=False,
                        size_hint_y=None, height=dp(44), **self.ti_style())
        box.add_widget(inp)

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
            self.save_settings()
            render()

        def add(*_):
            t = inp.text.strip()
            if t:
                self.settings["prefs"].append(t)
                self.save_settings()
                inp.text = ""
                render()
        inp.bind(on_text_validate=add)
        row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        row.add_widget(self.btn("Add", add, bg=CYAN, fg=BG))
        row.add_widget(self.btn("Close", pop.dismiss))
        box.add_widget(row)
        render()
        pop.open()

    # -------------------------------------------------------- voice/photo
    def start_voice(self, target):
        try:
            from android import activity
            from jnius import autoclass
            Intent = autoclass("android.content.Intent")
            RS = autoclass("android.speech.RecognizerIntent")
            intent = Intent(RS.ACTION_RECOGNIZE_SPEECH)
            intent.putExtra(RS.EXTRA_LANGUAGE_MODEL, RS.LANGUAGE_MODEL_FREE_FORM)

            def on_result(req, _res, data):
                if req != 4242:
                    return
                activity.unbind(on_activity_result=on_result)
                if data:
                    r = data.getStringArrayListExtra(RS.EXTRA_RESULTS)
                    if r and r.size():
                        txt = str(r.get(0))
                        Clock.schedule_once(lambda *_: setattr(target, "text", txt), 0)
            activity.bind(on_activity_result=on_result)
            autoclass("org.kivy.android.PythonActivity").mActivity.startActivityForResult(intent, 4242)
        except Exception:
            self.notice("Voice input", "Voice capture is not available in this environment. "
                                       "Tap the text box and use the microphone key on your keyboard instead.")

    def pick_photo(self, then):
        start = "/storage/emulated/0" if os.path.exists("/storage/emulated/0") else os.path.expanduser("~")
        fc = FileChooserListView(path=start, filters=["*.jpg", "*.jpeg", "*.png", "*.webp"])
        box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        box.add_widget(fc)
        row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        pop = Popup(title="Choose a photo", content=box, size_hint=(.95, .9), background_color=rgba(PANEL))

        def choose(*_):
            if fc.selection:
                self.pending_image = fc.selection[0]
                pop.dismiss()
                then()
        row.add_widget(self.btn("Attach", choose, bg=CYAN, fg=BG))
        row.add_widget(self.btn("Cancel", pop.dismiss))
        box.add_widget(row)
        pop.open()

    # --------------------------------------------------------------- chat
    def open_chat(self, prompt=None, send=False):
        self.go("chat")
        if prompt:
            self.input_box.text = prompt
            if send:
                Clock.schedule_once(self.send_chat, .15)

    def build_chat(self):
        p = self.page((10, 8))
        name = self.settings.get("assistant_name", "QYRONEX")
        hdr = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(6))
        hdr.add_widget(self.btn("<", lambda *_: self.go("home"), fs=18, size_hint=(None, 1), width=dp(44)))
        col = BoxLayout(orientation="vertical")
        col.add_widget(TLabel(text=f"[b]{name}[/b]", markup=True, font_size=sp(18)))
        self.status_label = TLabel(text="AI assistant", font_size=sp(12), color=rgba(MUTED))
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
        comp.add_widget(self.btn("+", lambda *_: self.pick_photo(self.refresh_attach), bg=PANEL2, fg=CYAN, fs=20,
                                 size_hint=(None, 1), width=dp(46)))
        self.input_box = TextInput(hint_text="Message QYRONEX...", multiline=True, **self.ti_style())
        self.input_box.bind(focus=lambda _i, f: f and self.scroll_bottom())
        comp.add_widget(self.input_box)
        comp.add_widget(self.btn("Send", self.send_chat, bg=CYAN, fg=BG, fs=13, size_hint=(None, 1), width=dp(58)))
        p.add_widget(comp)

        msgs = self.conv()["messages"]
        if not msgs:
            self.add_bubble("assistant", "Hi! I'm QYRONEX, your marketing AI assistant. Add your Gemini API key in "
                                         "AI Settings, then ask me anything. Tap + to attach a photo.", copy=False)
        for m in msgs:
            self.add_bubble(m.get("role", "assistant"), m.get("text", ""))
        self.refresh_attach()

    def refresh_attach(self):
        if self.screen != "chat":
            self.go("chat")
            return
        if self.pending_image:
            self.status_label.text = "Photo attached: " + os.path.basename(self.pending_image)[:24]
        else:
            self.status_label.text = "AI assistant"

    def scroll_bottom(self):
        Clock.schedule_once(lambda *_: self.screen == "chat" and setattr(self.chat_scroll, "scroll_y", 0), .15)

    def add_bubble(self, role, text, copy=True):
        user = role == "user"
        row = BoxLayout(size_hint_y=None)
        bub = Card(bg=USER_BUBBLE if user else AI_BUBBLE, orientation="vertical", size_hint=(.86, None),
                   padding=dp(10), spacing=dp(4))
        bub.bind(minimum_height=bub.setter("height"))
        bub.bind(height=lambda i, h: setattr(row, "height", h))
        who = "You" if user else self.settings.get("assistant_name", "QYRONEX")
        bub.add_widget(AutoLabel(text=f"[b]{who}[/b]", markup=True, font_size=sp(12),
                                 color=rgba(WHITE if user else CYAN)))
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
            self.notice("Please wait", "QYRONEX is still answering.")
            return
        text = self.input_box.text.strip()
        if not text and not self.pending_image:
            return
        text = text or "Describe and analyze this image."
        self.input_box.text = ""
        c = self.conv()
        if not c["messages"]:
            c["title"] = text[:40]
        c["messages"].append({"role": "user", "text": text})
        self.data["sent"] += 1
        self.save_data()
        self.add_bubble("user", text)
        history = c["messages"][:-1][-24:]
        img, self.pending_image = self.pending_image, None
        self.busy = True
        self.status_label.text = "QYRONEX is typing..."
        self.typing = self.add_bubble("assistant", "QYRONEX is typing...", copy=False)
        self.call_ai(text, history, lambda ans, ok: self.on_chat_reply(c, ans, ok), image=img)

    def on_chat_reply(self, c, answer, ok):
        self.busy = False
        if ok:
            c["messages"].append({"role": "assistant", "text": answer})
            self.save_data()
        if self.screen == "chat" and c is self.conv():
            try:
                self.chat_stack.remove_widget(self.typing)
            except Exception:
                pass
            self.add_bubble("assistant", answer)
            self.refresh_attach()

    # ------------------------------------------------------------- AI call
    def system_text(self):
        s = str(self.settings.get("instructions") or DEFAULT_INSTRUCTIONS)
        s += f"\nThe user's name is {self.settings.get('user_name') or 'unknown'}."
        prefs = self.settings.get("prefs") or []
        if prefs:
            s += "\n\nSaved user preferences (always follow them):\n" + "\n".join("- " + p for p in prefs)
        return s

    def call_ai(self, prompt, history, done, image=None):
        key = str(self.settings.get("api_key", "")).strip()
        if not key:
            Clock.schedule_once(lambda *_: done("The Gemini API key is missing. Open AI Settings and paste your key.", False), 0)
            return
        model = str(self.settings.get("model") or DEFAULT_MODEL).strip()
        system = self.system_text()
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
                    if len(raw) > 6000000:
                        raise ValueError("Image is too large (max about 6 MB).")
                    mime = mimetypes.guess_type(image)[0] or "image/jpeg"
                    parts.append({"inlineData": {"mimeType": mime, "data": base64.b64encode(raw).decode()}})
                contents.append({"role": "user", "parts": parts})
                payload = {"systemInstruction": {"parts": [{"text": system}]}, "contents": contents,
                           "generationConfig": {"temperature": temp, "maxOutputTokens": 1500}}
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
                req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST",
                                             headers={"Content-Type": "application/json", "x-goog-api-key": key})
                with urllib.request.urlopen(req, timeout=60) as resp:
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
                if ok:
                    self.bump_reply()
                done(answer, ok)
            Clock.schedule_once(finish, 0)
        threading.Thread(target=work, daemon=True).start()

    # --------------------------------------------------- reusable AI tool
    def ai_tool(self, page, hint, button, make_prompt, input_size=.25):
        box = TextInput(hint_text=hint, multiline=True, size_hint_y=input_size, **self.ti_style())
        page.add_widget(box)
        wrap = Card(bg=PANEL, padding=dp(10))
        sv = ScrollView(do_scroll_x=False)
        result = AutoLabel(text="Your result will appear here.", color=rgba(MUTED), font_size=sp(14))
        sv.add_widget(result)
        wrap.add_widget(sv)
        page.add_widget(wrap)

        def run(*_):
            if self.busy:
                self.notice("Please wait", "QYRONEX is still working on another request.")
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
            self.call_ai(prompt, [], done)
        row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        row.add_widget(self.btn(button, run, bg=CYAN, fg=BG))
        row.add_widget(self.btn("Copy", lambda *_: Clipboard.copy(result.text), size_hint_x=.5))
        row.add_widget(self.btn("To chat", lambda *_: self.open_chat(
            (box.text.strip() + "\n\n" + result.text)[:4000] if result.text.startswith(("1", "#", "*")) or len(result.text) > 30
            else box.text.strip()), size_hint_x=.6))
        page.add_widget(row)

    # ---------------------------------------------------------- campaigns
    def build_campaigns(self):
        p = self.page()
        p.add_widget(self.header("Campaigns"))
        ti = self.ti_style()
        form = Card(bg=PANEL, orientation="vertical", size_hint_y=None, height=dp(170), padding=dp(10), spacing=dp(6))
        name = TextInput(hint_text="Campaign name", multiline=False, size_hint_y=None, height=dp(44), **ti)
        goal = TextInput(hint_text="Goal / audience (optional)", multiline=False, size_hint_y=None, height=dp(44), **ti)
        form.add_widget(name)
        form.add_widget(goal)

        def add(*_):
            if not name.text.strip():
                self.notice("Name needed", "Give the campaign a name.")
                return
            self.data["campaigns"].append({"name": name.text.strip(), "goal": goal.text.strip()})
            self.save_data()
            name.text = goal.text = ""
            render()
        form.add_widget(self.btn("Create campaign", add, bg=CYAN, fg=BG, size_hint_y=None, height=dp(44)))
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
                r.add_widget(self.btn("Plan", lambda *_, pr=prompt: self.open_chat(pr, send=True), bg=BLUE, fs=12,
                                      size_hint_x=None, width=dp(56)))
                r.add_widget(self.btn("Del", lambda *_, i=i: delete(i), bg=RED, fs=12, size_hint_x=None, width=dp(50)))
                grid.add_widget(r)
        render()

    # ------------------------------------------------------------ content
    def build_content(self):
        p = self.page()
        p.add_widget(self.header("Generate Content"))
        row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        btns = []

        def pick(i):
            self.ctype = i
            for j, b in enumerate(btns):
                b.lbl.color = rgba(BG if j == i else WHITE)
                b._rect.pos = b.pos
            for j, b in enumerate(btns):
                b.canvas.before.clear()
                with b.canvas.before:
                    Color(*rgba(CYAN if j == i else PANEL2))
                    b._rect = RoundedRectangle(pos=b.pos, size=b.size, radius=[dp(14)])
        for i, (label, _) in enumerate(CONTENT_TYPES):
            b = self.btn(label, None, fs=12)
            b.bind(on_release=lambda _i, i=i: pick(i))
            btns.append(b)
            row.add_widget(b)
        p.add_widget(row)
        Clock.schedule_once(lambda *_: pick(self.ctype), .05)
        self.ai_tool(p, "What is it about? e.g. launch of our new coffee brand",
                     "Generate", lambda t: (CONTENT_TYPES[self.ctype][1] + t) if t else None, .2)

    # ---------------------------------------------------------- analytics
    def build_analytics(self):
        p = self.page()
        p.add_widget(self.header("Analyze Performance"))
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
                                "3 concrete next actions:\n\n" + t) if t else None, .3)

    # ----------------------------------------------------------- settings
    def build_settings(self):
        p = self.page()
        p.add_widget(self.header("AI Settings"))
        sv = ScrollView(do_scroll_x=False)
        g = GridLayout(cols=1, size_hint_y=None, spacing=dp(6), padding=(0, 0, 0, dp(12)))
        g.bind(minimum_height=g.setter("height"))
        ti = self.ti_style()

        def field(label, value, h=44, **kw):
            g.add_widget(AutoLabel(text=label, color=rgba(MUTED), font_size=sp(12)))
            w = TextInput(text=str(value), multiline=kw.pop("multiline", False), size_hint_y=None,
                          height=dp(h), **ti, **kw)
            g.add_widget(w)
            return w
        user = field("Your name", self.settings.get("user_name", ""))
        name = field("Assistant display name", self.settings.get("assistant_name", "QYRONEX"))
        key = field("Gemini API key (keep private)", self.settings.get("api_key", ""), password=True,
                    hint_text="Paste API key here")
        model = field("Model name", self.settings.get("model", DEFAULT_MODEL))
        instr = field("System instructions (main way to change AI behaviour)",
                      self.settings.get("instructions", DEFAULT_INSTRUCTIONS), h=150, multiline=True)
        temp = field("Temperature 0-1 (lower = steadier, higher = more varied)",
                     self.settings.get("temperature", 0.7), input_filter="float")

        def save(*_):
            self.settings["user_name"] = user.text.strip() or "Alex"
            self.settings["assistant_name"] = name.text.strip() or "QYRONEX"
            self.settings["api_key"] = key.text.strip()
            self.settings["model"] = model.text.strip() or DEFAULT_MODEL
            self.settings["instructions"] = instr.text.strip() or DEFAULT_INSTRUCTIONS
            try:
                self.settings["temperature"] = max(0.0, min(1.0, float(temp.text or "0.7")))
            except ValueError:
                self.settings["temperature"] = 0.7
            self.save_settings()
            self.notice("Saved", "Your settings were saved on this device.")

        def reset(*_):
            instr.text = DEFAULT_INSTRUCTIONS
        g.add_widget(self.btn("Save settings", save, bg=CYAN, fg=BG, size_hint_y=None, height=dp(48)))
        g.add_widget(self.btn("Reset instructions", reset, size_hint_y=None, height=dp(44)))
        g.add_widget(self.btn("Teach the AI (preferences)", lambda *_: self.show_prefs(), bg=RED, size_hint_y=None, height=dp(44)))
        g.add_widget(self.btn("Clear chat history", lambda *_: self.clear_history(), size_hint_y=None, height=dp(44)))
        sv.add_widget(g)
        p.add_widget(sv)


if __name__ == "__main__":
    QYRONEXAIApp().run()
