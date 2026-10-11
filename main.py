"""
QYRONEX AI — standalone Kivy prototype
Run in Pydroid 3 after installing Kivy.
For a public/released app, move API calls to a secure backend; do not publish your API key.
"""
import json
import os
import threading
import urllib.request
import urllib.error

from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.core.window import Window
from kivy.utils import get_color_from_hex
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.popup import Popup
from kivy.uix.widget import Widget
from kivy.graphics import Color, Ellipse, Line, PushMatrix, PopMatrix, Rotate
from kivy.animation import Animation
from kivy.uix.image import Image

APP_NAME = "QYRONEX AI"
DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_INSTRUCTIONS = (
    "You are QYRONEX, a helpful, friendly, honest AI assistant inside the QYRONEX AI app. "
    "Answer clearly, adapt to the user's preferred style, ask a question when a request is unclear, "
    "and never pretend you completed an action that you did not complete."
)

BG = "#090A10"
PANEL = "#151622"
PANEL2 = "#202130"
CYAN = "#20E4DC"
WHITE = "#F5F6FC"
MUTED = "#A8A9BB"
USER_BUBBLE = "#153D43"
AI_BUBBLE = "#1A1B28"

def rgba(hex_color):
    return get_color_from_hex(hex_color)

class RoundButton(Button):
    def __init__(self, **kwargs):
        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("background_down", "")
        kwargs.setdefault("background_color", rgba(CYAN))
        kwargs.setdefault("color", rgba(BG))
        kwargs.setdefault("bold", True)
        super().__init__(**kwargs)

class QYRONEXAIApp(App):
    def build(self):
        self.title = APP_NAME
        Window.clearcolor = rgba(BG)
        # Resize/pan the app when Android's keyboard opens, keeping the composer visible.
        try:
            Window.softinput_mode = "below_target"
        except Exception:
            pass
        self.config_path = os.path.join(self.user_data_dir, "qyronex_settings.json")
        self.history_path = os.path.join(self.user_data_dir, "qyronex_history.json")
        self.settings = {"api_key": "", "model": DEFAULT_MODEL,
                         "instructions": DEFAULT_INSTRUCTIONS, "assistant_name": "QYRONEX",
                         "temperature": 0.7}
        self.messages = []
        self.conversations = []
        self.busy = False
        self.load_local_data()
        self.root = BoxLayout(orientation="vertical")
        self.show_boot_screen()
        return self.root

    def show_boot_screen(self):
        self.root.clear_widgets()
        screen = BoxLayout(orientation="vertical", spacing=dp(12), padding=dp(20))
        screen.add_widget(Widget())
        logo_path = os.path.join(os.path.dirname(__file__), "qyronex_logo.png")
        if os.path.exists(logo_path):
            logo = Image(source=logo_path, size_hint=(1, .72), allow_stretch=True, keep_ratio=True)
            screen.add_widget(logo)
        else:
            screen.add_widget(Label(text="[b]QYRONEX[/b]", markup=True, color=rgba(CYAN), font_size="34sp"))
        ring = Widget(size_hint=(None, None), size=(dp(110), dp(110)), pos_hint={"center_x": .5})
        with ring.canvas:
            Color(*rgba(CYAN)); ring.outer = Line(circle=(0, 0, dp(43)), width=2.5)
            Color(0.0, 0.85, 1.0, 1); ring.inner = Line(circle=(0, 0, dp(28)), width=3)
        def place_rings(*_):
            cx, cy = ring.center
            ring.outer.circle = (cx, cy, dp(43))
            ring.inner.circle = (cx, cy, dp(28))
        ring.bind(pos=place_rings, size=place_rings)
        place_rings()
        screen.add_widget(ring)
        screen.add_widget(Label(text="AI ASSISTANT  •  INITIALIZING", color=rgba(MUTED), font_size="12sp", size_hint_y=None, height=dp(30)))
        screen.add_widget(Widget())
        self.root.add_widget(screen)
        # Opposing ring rotation runs for five seconds, then opens the home screen.
        self._boot_start = Clock.get_time()
        def animate(_dt):
            elapsed = Clock.get_time() - self._boot_start
            angle = (elapsed * 150) % 360
            ring.canvas.before.clear()
            with ring.canvas.before:
                PushMatrix(); Rotate(angle=angle, origin=ring.center)
            ring.canvas.after.clear()
            with ring.canvas.after:
                PopMatrix()
            ring.inner.circle = (ring.center_x, ring.center_y, dp(28))
            ring.outer.circle = (ring.center_x, ring.center_y, dp(43))
            if elapsed >= 5:
                Clock.unschedule(animate)
                self.show_home()
        Clock.schedule_interval(animate, 1 / 30)

    def dashboard_card(self, title, subtitle, symbol, color, callback):
        card = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(5))
        with card.canvas.before:
            from kivy.graphics import Color, RoundedRectangle
            Color(*rgba(color))
            card.bg = RoundedRectangle(pos=card.pos, size=card.size, radius=[dp(16)])
        card.bind(pos=lambda inst, val: setattr(inst.bg, "pos", val),
                  size=lambda inst, val: setattr(inst.bg, "size", val))
        icon = Label(text=f"[b]{symbol}[/b]", markup=True, color=rgba(WHITE), font_size="27sp",
                     size_hint_y=None, height=dp(38), halign="left")
        card.add_widget(icon)
        card.add_widget(Label(text=f"[b]{title}[/b]", markup=True, color=rgba(WHITE),
                              font_size="15sp", size_hint_y=None, height=dp(25), halign="left"))
        card.add_widget(Label(text=subtitle, color=rgba(WHITE), font_size="11sp",
                              halign="left", valign="top", text_size=(dp(135), None)))
        btn = Button(text="Open  ›", size_hint_y=None, height=dp(32), background_normal="",
                     background_color=(0, 0, 0, .16), color=rgba(WHITE))
        btn.bind(on_release=callback)
        card.add_widget(btn)
        return card

    def show_home(self):
        """QYRONEX dashboard inspired by the supplied first-screen mockup."""
        self.root.clear_widgets()
        page = BoxLayout(orientation="vertical", padding=(dp(12), dp(8)), spacing=dp(8))
        # Header and brand
        header = BoxLayout(size_hint_y=None, height=dp(54), spacing=dp(8))
        menu = Button(text="⠿", size_hint_x=None, width=dp(42), background_normal="",
                      background_color=rgba(PANEL2), color=rgba(CYAN), font_size="24sp")
        menu.bind(on_release=lambda *_: self.open_settings())
        header.add_widget(menu)
        brand = BoxLayout(orientation="vertical")
        brand.add_widget(Label(text="[b]QYRONEX[/b]", markup=True, color=rgba(CYAN),
                               font_size="22sp", halign="left", valign="bottom"))
        brand.add_widget(Label(text="AI ASSISTANT  •  CONTROL CENTRE", color=rgba(MUTED),
                               font_size="10sp", halign="left", valign="top"))
        header.add_widget(brand)
        settings = Button(text="☰", size_hint_x=None, width=dp(42), background_normal="",
                          background_color=rgba(PANEL2), color=rgba(CYAN), font_size="22sp")
        settings.bind(on_release=lambda *_: self.open_settings())
        header.add_widget(settings)
        page.add_widget(header)
        logo_path = os.path.join(os.path.dirname(__file__), "qyronex_logo.png")
        if os.path.exists(logo_path):
            brand_art = Image(source=logo_path, size_hint_y=None, height=dp(138), allow_stretch=True, keep_ratio=True)
            page.add_widget(brand_art)

        welcome = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(76),
                            padding=(dp(14), dp(8)), spacing=dp(2))
        with welcome.canvas.before:
            from kivy.graphics import Color, RoundedRectangle
            Color(*rgba("#172D50")); welcome.bg = RoundedRectangle(pos=welcome.pos, size=welcome.size, radius=[dp(16)])
        welcome.bind(pos=lambda inst, val: setattr(inst.bg, "pos", val),
                     size=lambda inst, val: setattr(inst.bg, "size", val))
        welcome.add_widget(Label(text="[b]Hello![/b]", markup=True, color=rgba(WHITE), font_size="21sp", halign="left"))
        welcome.add_widget(Label(text="What would you like QYRONEX to help you with today?", color=rgba(MUTED), font_size="12sp", halign="left"))
        page.add_widget(welcome)

        cards = GridLayout(cols=2, spacing=dp(8), size_hint_y=None, row_default_height=dp(150), row_force_default=True)
        cards.bind(minimum_height=cards.setter("height"))
        cards.add_widget(self.dashboard_card("Create Campaign", "Plan a new campaign or strategy", "+", "#176ED1", lambda *_: self.open_chat_with("Help me create a campaign plan. Ask me for the goal and audience.")))
        cards.add_widget(self.dashboard_card("Generate Content", "Draft posts, ads and blog ideas", "✎", "#119B72", lambda *_: self.open_chat_with("Help me generate content. Ask what platform and topic I want.")))
        cards.add_widget(self.dashboard_card("Analyze Performance", "Review data I provide", "▥", "#E0A51B", lambda *_: self.show_notice("Analyze Performance", "Share your campaign metrics or paste a report in chat. Live analytics require a connected service and permission.")))
        cards.add_widget(self.dashboard_card("Manage Insights", "Change AI behaviour and settings", "⚙", "#D94856", lambda *_: self.open_settings()))
        page.add_widget(cards)

        askrow = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(6), padding=(dp(2), 0))
        ask = Button(text="⌕  Ask QYRONEX…", halign="left", background_normal="",
                     background_color=rgba(PANEL2), color=rgba(MUTED))
        ask.bind(on_release=lambda *_: self.show_chat_screen())
        askrow.add_widget(ask)
        voice = Button(text="➤", size_hint_x=None, width=dp(52), background_normal="",
                       background_color=rgba(CYAN), color=rgba(BG), font_size="20sp")
        voice.bind(on_release=lambda *_: self.show_chat_screen())
        askrow.add_widget(voice)
        page.add_widget(askrow)

        page.add_widget(Label(text="[b]Quick access[/b]", markup=True, color=rgba(WHITE),
                              font_size="15sp", size_hint_y=None, height=dp(25), halign="left"))
        quick = GridLayout(cols=2, spacing=dp(7), size_hint_y=None, height=dp(48))
        for label, action in [("Open Chat", lambda *_: self.show_chat_screen()),
                              ("Connect SAM NG", lambda *_: self.show_notice("Connect SAM NG", "To make a real connection, QYRONEX needs a SAM NG API or a documented integration endpoint. The button is ready, but the connection cannot be completed until those details are available."))]:
            b = Button(text=label, background_normal="", background_color=rgba(PANEL2), color=rgba(CYAN))
            b.bind(on_release=action); quick.add_widget(b)
        page.add_widget(quick)

        nav = GridLayout(cols=4, size_hint_y=None, height=dp(48), spacing=dp(3))
        for label, action in [("⌂ Home", lambda *_: self.show_home()),
                              ("✦ Chat", lambda *_: self.show_chat_screen()),
                              ("▥ Insights", lambda *_: self.show_notice("Insights", "Paste performance data into QYRONEX chat to analyze it.")),
                              ("⚙ Settings", lambda *_: self.open_settings())]:
            b = Button(text=label, background_normal="", background_color=rgba("#111D38"), color=rgba(MUTED), font_size="11sp")
            b.bind(on_release=action); nav.add_widget(b)
        page.add_widget(nav)
        self.root.add_widget(page)

    def open_chat_with(self, prompt):
        self.show_chat_screen()
        Clock.schedule_once(lambda *_: setattr(self.input_box, "text", prompt), .1)

    def show_chat_screen(self):
        self.root.clear_widgets()
        layout = BoxLayout(orientation="horizontal", spacing=dp(0))
        self.history_panel = BoxLayout(orientation="vertical", size_hint_x=None, width=dp(0), padding=dp(8), spacing=dp(8))
        self.history_panel.add_widget(Label(text="[b]CHAT HISTORY[/b]", markup=True, color=rgba(CYAN), size_hint_y=None, height=dp(36)))
        new_btn = Button(text="+ New chat", size_hint_y=None, height=dp(42), background_normal="", background_color=rgba(PANEL2), color=rgba(WHITE))
        new_btn.bind(on_release=lambda *_: self.new_chat())
        self.history_panel.add_widget(new_btn)
        self.history_list = BoxLayout(orientation="vertical", spacing=dp(5), size_hint_y=None)
        self.history_list.bind(minimum_height=self.history_list.setter("height"))
        hist_scroll = ScrollView(do_scroll_x=False)
        hist_scroll.add_widget(self.history_list)
        self.history_panel.add_widget(hist_scroll)
        layout.add_widget(self.history_panel)
        main = BoxLayout(orientation="vertical", padding=(dp(10), dp(8)), spacing=dp(8))
        header = BoxLayout(size_hint_y=None, height=dp(56), spacing=dp(8))
        menu_btn = Button(text="⌂", size_hint=(None, 1), width=dp(44), background_normal="", background_color=rgba(PANEL2), color=rgba(CYAN), font_size="22sp")
        menu_btn.bind(on_release=lambda *_: self.show_home())
        header.add_widget(menu_btn)
        title_col = BoxLayout(orientation="vertical")
        title_col.add_widget(Label(text="[b]QYRONEX[/b]", markup=True, color=rgba(WHITE), font_size="18sp", halign="left", valign="bottom", text_size=(Window.width, None)))
        self.status_label = Label(text="AI assistant", color=rgba(MUTED), font_size="12sp", halign="left", valign="top")
        title_col.add_widget(self.status_label); header.add_widget(title_col)
        settings_btn = Button(text="⚙", size_hint=(None, 1), width=dp(44), font_size="24sp", background_normal="", background_color=rgba(PANEL2), color=rgba(CYAN))
        settings_btn.bind(on_release=lambda *_: self.open_settings()); header.add_widget(settings_btn)
        main.add_widget(header)
        self.chat_scroll = ScrollView(do_scroll_x=False, bar_width=dp(3), scroll_type=["bars", "content"])
        self.chat_stack = GridLayout(cols=1, size_hint_y=None, spacing=dp(10), padding=(dp(2), dp(8)))
        self.chat_stack.bind(minimum_height=self.chat_stack.setter("height")); self.chat_scroll.add_widget(self.chat_stack)
        main.add_widget(self.chat_scroll)
        composer = BoxLayout(size_hint_y=None, height=dp(56), spacing=dp(7), padding=(0, dp(2)))
        self.input_box = TextInput(hint_text="Message QYRONEX…", multiline=True, size_hint_y=1,
            background_normal="", background_active="", background_color=rgba(PANEL2),
            foreground_color=rgba(WHITE), hint_text_color=rgba(MUTED), cursor_color=rgba(CYAN),
            padding=(dp(12), dp(12)), font_size="15sp")
        self.input_box.bind(on_text_validate=self.send_message, focus=self.on_composer_focus)
        composer.add_widget(self.input_box)
        self.send_btn = RoundButton(text="➤", size_hint=(None, 1), width=dp(54), font_size="20sp")
        self.send_btn.bind(on_release=self.send_message); composer.add_widget(self.send_btn)
        main.add_widget(composer)
        layout.add_widget(main); self.root.add_widget(layout)
        if not self.messages:
            self.messages = [{"role": "assistant", "text": "Hi! I'm QYRONEX, your AI assistant. Open ⚙ Settings to add your Gemini API key and customise how I behave."}]
            self.save_history()
        for item in self.messages:
            self.add_message(item.get("role", "assistant"), item.get("text", ""), save=False)
        self.refresh_history()

    def on_composer_focus(self, _instance, focused):
        if focused:
            Clock.schedule_once(lambda *_: setattr(self.chat_scroll, "scroll_y", 0), .2)

    def toggle_history(self):
        self.history_panel.width = dp(220) if self.history_panel.width < dp(10) else dp(0)

    def refresh_history(self):
        if not hasattr(self, "history_list"):
            return
        self.history_list.clear_widgets()
        previews = []
        for m in self.messages:
            if m.get("role") == "user":
                previews.append(m.get("text", "New chat"))
        if not previews:
            previews = ["New conversation"]
        for preview in previews[-20:][::-1]:
            b = Button(text=preview[:32], size_hint_y=None, height=dp(42), halign="left", background_normal="", background_color=rgba(PANEL2), color=rgba(WHITE))
            self.history_list.add_widget(b)

    def new_chat(self):
        self.messages = []
        self.save_history()
        if hasattr(self, "chat_stack"):
            self.chat_stack.clear_widgets()
            self.add_message("assistant", "New chat started. What would you like to explore?")
            self.refresh_history()

    def load_local_data(self):
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                self.settings.update({k: v for k, v in saved.items() if k in self.settings})
        except Exception:
            pass
        try:
            if os.path.exists(self.history_path):
                with open(self.history_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.messages = data if isinstance(data, list) else []
        except Exception:
            self.messages = []

    def save_settings(self):
        try:
            os.makedirs(self.user_data_dir, exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            self.show_notice("Could not save settings", str(exc))

    def save_history(self):
        try:
            os.makedirs(self.user_data_dir, exist_ok=True)
            with open(self.history_path, "w", encoding="utf-8") as f:
                json.dump(self.messages[-120:], f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def add_message(self, role, text, save=True):
        is_user = role == "user"
        outer = BoxLayout(orientation="horizontal", size_hint_y=None, padding=(dp(2), 0))
        if is_user:
            outer.add_widget(Widget())
        bubble = BoxLayout(orientation="vertical", size_hint=(0.88, None), padding=dp(11), spacing=dp(3))
        bubble.canvas.before.clear()
        with bubble.canvas.before:
            from kivy.graphics import Color, RoundedRectangle
            Color(*rgba(USER_BUBBLE if is_user else AI_BUBBLE))
            bubble.bg = RoundedRectangle(pos=bubble.pos, size=bubble.size, radius=[dp(14)])
        bubble.bind(pos=lambda inst, val: setattr(inst.bg, "pos", val),
                    size=lambda inst, val: setattr(inst.bg, "size", val))
        who = "You" if is_user else self.settings.get("assistant_name", "QYRONEX")
        head = Label(text=f"[b]{who}[/b]", markup=True, color=rgba(CYAN if not is_user else WHITE),
                     font_size="12sp", size_hint_y=None, height=dp(19), halign="left",
                     text_size=(Window.width * .72, None))
        body = Label(text=str(text), color=rgba(WHITE), font_size="15sp", size_hint_y=None,
                     halign="left", valign="top", markup=False, text_size=(Window.width * .70, None))
        def fit_body(*_):
            body.text_size = (max(dp(120), bubble.width - dp(22)), None)
            body.texture_update()
            body.height = max(dp(22), body.texture_size[1])
        bubble.bind(width=fit_body)
        body.bind(texture_size=lambda inst, val: setattr(inst, "height", max(dp(22), val[1])))
        bubble.add_widget(head)
        bubble.add_widget(body)
        def fit_bubble(*_):
            bubble.height = head.height + body.height + dp(30)
            outer.height = bubble.height
        bubble.bind(minimum_height=fit_bubble)
        fit_body()
        fit_bubble()
        outer.add_widget(bubble)
        if not is_user:
            outer.add_widget(Widget())
        self.chat_stack.add_widget(outer)
        if save:
            self.messages.append({"role": role, "text": str(text)})
            self.messages = self.messages[-120:]
            self.save_history()
            self.refresh_history()
        Clock.schedule_once(lambda *_: setattr(self.chat_scroll, "scroll_y", 0), .12)

    def send_message(self, *_):
        if self.busy:
            return
        prompt = self.input_box.text.strip()
        if not prompt:
            return
        self.input_box.text = ""
        self.add_message("user", prompt)
        key = self.settings.get("api_key", "").strip()
        if not key:
            self.add_message("assistant", "I’m ready, but the Gemini API key is missing. Tap ⚙ Settings and paste your key in the API key field.")
            return
        self.busy = True
        self.send_btn.disabled = True
        self.status_label.text = "QYRONEX is typing…"
        self.add_message("assistant", "QYRONEX is typing…")
        history = list(self.messages[:-1])[-24:]
        threading.Thread(target=self.request_reply, args=(prompt, history, key), daemon=True).start()

    def request_reply(self, prompt, history, key):
        answer = ""
        try:
            model = str(self.settings.get("model") or DEFAULT_MODEL).strip()
            instruction = str(self.settings.get("instructions") or DEFAULT_INSTRUCTIONS)
            contents = []
            for item in history:
                role = "user" if item.get("role") == "user" else "model"
                txt = item.get("text", "")
                if txt and txt != "QYRONEX is typing…":
                    contents.append({"role": role, "parts": [{"text": str(txt)}]})
            contents.append({"role": "user", "parts": [{"text": prompt}]})
            payload = {
                "systemInstruction": {"parts": [{"text": instruction}]},
                "contents": contents,
                "generationConfig": {
                    "temperature": float(self.settings.get("temperature", 0.7)),
                    "maxOutputTokens": 1200
                }
            }
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                         headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=45) as response:
                result = json.loads(response.read().decode("utf-8"))
            candidates = result.get("candidates", [])
            if candidates:
                answer = "".join(part.get("text", "") for part in candidates[0].get("content", {}).get("parts", []))
            if not answer:
                answer = "The AI service returned an empty response. Try again."
        except urllib.error.HTTPError as exc:
            try:
                details = exc.read().decode("utf-8")[:700]
            except Exception:
                details = str(exc)
            answer = f"Gemini API error ({exc.code}). Check the API key, model name, or API quota.\n{details}"
        except Exception as exc:
            answer = f"Couldn't reach Gemini. Check your internet connection and API key.\n{exc}"
        Clock.schedule_once(lambda *_: self.finish_reply(answer), 0)

    def finish_reply(self, answer):
        # Remove the temporary typing bubble only.
        for child in list(self.chat_stack.children):
            labels = [w for w in child.walk() if isinstance(w, Label)]
            if any("QYRONEX is typing…" in label.text for label in labels):
                self.chat_stack.remove_widget(child)
                break
        self.add_message("assistant", answer)
        self.busy = False
        self.send_btn.disabled = False
        self.status_label.text = "AI assistant"

    def open_settings(self):
        form = BoxLayout(orientation="vertical", spacing=dp(9), padding=dp(14))
        form.add_widget(Label(text="Customise how your AI works", color=rgba(WHITE),
                              font_size="18sp", size_hint_y=None, height=dp(32)))
        form.add_widget(Label(text="Assistant display name", color=rgba(MUTED),
                              size_hint_y=None, height=dp(20), halign="left"))
        name_input = TextInput(text=str(self.settings.get("assistant_name", "QYRONEX")),
                               multiline=False, size_hint_y=None, height=dp(44),
                               background_color=rgba(PANEL2), foreground_color=rgba(WHITE),
                               cursor_color=rgba(CYAN))
        form.add_widget(name_input)
        form.add_widget(Label(text="Gemini API key (keep private)", color=rgba(MUTED),
                              size_hint_y=None, height=dp(20), halign="left"))
        key_input = TextInput(text=str(self.settings.get("api_key", "")), password=True,
                              multiline=False, size_hint_y=None, height=dp(44),
                              background_color=rgba(PANEL2), foreground_color=rgba(WHITE),
                              cursor_color=rgba(CYAN), hint_text="Paste API key here")
        form.add_widget(key_input)
        form.add_widget(Label(text="Model name", color=rgba(MUTED),
                              size_hint_y=None, height=dp(20), halign="left"))
        model_input = TextInput(text=str(self.settings.get("model", DEFAULT_MODEL)),
                                multiline=False, size_hint_y=None, height=dp(44),
                                background_color=rgba(PANEL2), foreground_color=rgba(WHITE),
                                cursor_color=rgba(CYAN))
        form.add_widget(model_input)
        form.add_widget(Label(text="System instructions — this is the main way you change AI behaviour",
                              color=rgba(MUTED), size_hint_y=None, height=dp(38),
                              halign="left", valign="middle"))
        instructions_input = TextInput(text=str(self.settings.get("instructions", DEFAULT_INSTRUCTIONS)),
                                       multiline=True, background_color=rgba(PANEL2),
                                       foreground_color=rgba(WHITE), cursor_color=rgba(CYAN),
                                       padding=dp(10))
        form.add_widget(instructions_input)
        form.add_widget(Label(text="Temperature: lower = steadier, higher = more varied",
                              color=rgba(MUTED), size_hint_y=None, height=dp(22)))
        temp_row = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(8))
        temp_input = TextInput(text=str(self.settings.get("temperature", 0.7)), multiline=False,
                               input_filter="float", size_hint_y=None, height=dp(42),
                               background_color=rgba(PANEL2), foreground_color=rgba(WHITE))
        temp_row.add_widget(temp_input)
        form.add_widget(temp_row)
        form.add_widget(Label(text="Account & connected apps", color=rgba(CYAN), size_hint_y=None, height=dp(26)))
        connect_btn = Button(text="Sign in / connect apps on this phone", size_hint_y=None, height=dp(44), background_normal="", background_color=rgba(PANEL2), color=rgba(WHITE))
        form.add_widget(connect_btn)
        form.add_widget(Label(text="Connection setup is a placeholder: each service needs its own secure sign-in and permission flow.", color=rgba(MUTED), size_hint_y=None, height=dp(38), halign="left", valign="middle"))
        actions = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        save_btn = RoundButton(text="Save settings")
        actions.add_widget(save_btn)
        close_btn = Button(text="Cancel", background_normal="", background_color=rgba(PANEL2),
                           color=rgba(WHITE))
        actions.add_widget(close_btn)
        form.add_widget(actions)
        popup = Popup(title="AI Control Centre", content=form, size_hint=(.94, .92),
                      background_color=rgba(PANEL))
        def save_and_close(*_):
            self.settings["assistant_name"] = name_input.text.strip() or "QYRONEX"
            self.settings["api_key"] = key_input.text.strip()
            self.settings["model"] = model_input.text.strip() or DEFAULT_MODEL
            self.settings["instructions"] = instructions_input.text.strip() or DEFAULT_INSTRUCTIONS
            try:
                self.settings["temperature"] = max(0.0, min(1.0, float(temp_input.text or "0.7")))
            except ValueError:
                self.settings["temperature"] = 0.7
            self.save_settings()
            self.status_label.text = f"{self.settings['assistant_name']} assistant"
            popup.dismiss()
            self.show_notice("Settings saved", "Your AI instructions and settings have been saved on this device.")
        def connect_apps(*_):
            self.show_notice("Connect apps", "This prototype does not yet sign in to Google or other phone apps. Each connection must be implemented with that service's official secure sign-in and user permissions.")
        connect_btn.bind(on_release=connect_apps)
        save_btn.bind(on_release=save_and_close)
        close_btn.bind(on_release=popup.dismiss)
        popup.open()

    def show_notice(self, title, message):
        box = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(12))
        box.add_widget(Label(text=message, color=rgba(WHITE)))
        btn = RoundButton(text="OK", size_hint_y=None, height=dp(44))
        box.add_widget(btn)
        pop = Popup(title=title, content=box, size_hint=(.88, .38), background_color=rgba(PANEL))
        btn.bind(on_release=pop.dismiss)
        pop.open()

    def on_stop(self):
        self.save_history()
        self.save_settings()

if __name__ == "__main__":
    QYRONEXAIApp().run()
