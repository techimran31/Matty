"""
matty_ui.py - Animated on-screen assistant for Matty (the classic window).

READING GUIDE
-------------
    main()
      +-- MattyUI(...)            the window itself (customtkinter)
            STEP 1  __init__      build the widgets, then start 3 timers
            STEP 2  voice_loop    background thread: mic -> text -> reply
            STEP 3  events queue  thread-safe mailbox from voice_loop to the UI
            STEP 4  poll_events   drains that mailbox 4x per second
            STEP 5  _animate      redraws the orb + waveform ~20x per second
            STEP 6  speak         text-to-speech on its own thread

Note: voice_loop() contains its own six numbered steps (key, microphone,
listening, wake word, thinking, speaking). Those are the inside of STEP 2.

WHY THE EVENTS QUEUE:
Tkinter widgets may only be touched from the thread that created them. The
voice loop therefore never calls self.log() directly - it puts a tuple into
self.events and poll_events() applies it on the UI thread.

matty_hud.py is the same program with a web page as the front end instead of
tkinter widgets.
"""

import math
import os
import queue
import threading
import time
import webbrowser
from tkinter import simpledialog
import tkinter as tk

import customtkinter as ctk
import speech_recognition as sr

import matty_actions
import matty_brain
import matty_config
from matty_voice import (
    BARGE_IN,
    SESSION_SECONDS,
    SPEECH_ACTIVE,
    SpeechUnavailable,
    audio_level,
    ensure_api_key,
    extract_wake,
    flush_stream,
    open_microphone,
    recognize_detailed,
    register_stop_hook,
    stop_speaking,
    tap_levels,
    user_is_talking,
    _tuned_recognizer,
)

APP_DIR = os.path.dirname(os.path.abspath(__file__))
HUD_PATH = os.path.join(APP_DIR, "matty_workplace.html")

BG = "#070b10"
PANEL = "#0f1720"
PANEL_2 = "#162230"
TEXT = "#d7e2ee"
MUTED = "#8b9bad"
ACCENT = "#00e5ff"
GREEN = "#7dffb0"
AMBER = "#ffb020"
RED = "#ff4d6d"

# ---------------------------------------------------------------------------
# STEP 6 - Speech output (queue + worker thread)
# ---------------------------------------------------------------------------
# Speaking takes seconds, so it never happens on the UI thread. Replies are
# queued and one daemon worker speaks them in order. SAPI on Windows,
# pyttsx3 everywhere else.

_tts_queue = queue.Queue()
_tts_thread = None
_tts_lock = threading.Lock()


def _tts_worker():
    """Speak queued sentences forever (COM is initialised on this thread).

    SPEECH_ACTIVE is set while audio is playing, so the voice loop stays deaf
    to Matty's own voice. The registered stop hook lets the user interrupt.
    """
    try:
        import pythoncom

        pythoncom.CoInitialize()
    except Exception:
        pass

    voice = None
    try:
        import win32com.client

        voice = win32com.client.Dispatch("SAPI.SpVoice")
    except Exception:
        voice = None

    def _silence():
        """Drop queued sentences and purge the current one."""
        while not _tts_queue.empty():
            try:
                _tts_queue.get_nowait()
                _tts_queue.task_done()
            except queue.Empty:
                break
        try:
            if voice is not None:
                voice.Speak("", 3)  # 3 = async + purge
        except Exception:
            pass

    register_stop_hook(_silence)

    while True:
        text = _tts_queue.get()
        if text is None:
            break
        SPEECH_ACTIVE.set()
        try:
            if voice is not None:
                voice.Speak(text)
            else:
                import pyttsx3

                engine = pyttsx3.init()
                engine.say(text)
                engine.runAndWait()
        except Exception as e:
            print("TTS error:", e, flush=True)
        finally:
            SPEECH_ACTIVE.clear()
            _tts_queue.task_done()


def speak(text):
    """Queue text for speech without blocking the interface."""
    global _tts_thread
    if not text:
        return
    with _tts_lock:
        if _tts_thread is None or not _tts_thread.is_alive():
            _tts_thread = threading.Thread(target=_tts_worker, daemon=True)
            _tts_thread.start()
    _tts_queue.put(text)


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------


class MattyUI(ctk.CTk):
    """The Matty window: header, reactor orb, transcript, quick actions."""

    # Status word -> colour used by the badge and the orb
    STATUS_COLORS = {
        "STANDBY": AMBER,
        "ACTIVE": ACCENT,
        "PROCESSING": AMBER,
        "SPEAKING": GREEN,
        "STOPPED": MUTED,
        "NO MIC": RED,
    }

    def __init__(self):
        """STEP 1 - create the window, the shared state and the 3 timers."""
        super().__init__()
        self.title("Matty Assistant")
        self.geometry("900x700")
        self.minsize(760, 580)
        self.configure(fg_color=BG)
        try:
            # Stay above other windows so the user can always see the status.
            self.attributes("-topmost", True)
        except Exception:
            pass

        # Shared state (written by the voice thread, read by the UI thread)
        self.events = queue.Queue()   # STEP 3 - mailbox voice_loop -> UI
        self.listening = False
        self.thread = None
        self.active_until = 0.0       # end of the 2 minute wake session
        self.speaking_until = 0.0     # while > now, show SPEAKING
        self.anim_state = "STANDBY"
        self.phase = 0.0              # animation time offset
        self.mic_level = 0            # live microphone loudness, 0-100

        # Build the four screen areas
        self._build_header()
        self._build_hero()
        self._build_body()
        self._build_footer()

        self.log("Matty is ready. Say 'Hello Matty' to activate.", "sys")
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # Three repeating jobs, all owned by tkinter's event loop:
        self.after(250, self.start_listening)  # STEP 2 - start voice thread
        self.after(100, self.poll_events)      # STEP 4 - drain the mailbox
        self.after(50, self._animate)          # STEP 5 - redraw the orb

    # ---------- layout ----------

    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=26, pady=(18, 0))

        ctk.CTkLabel(
            header,
            text="MATTY",
            font=ctk.CTkFont(size=36, weight="bold"),
            text_color=ACCENT,
        ).pack(side="left")

        ctk.CTkLabel(
            header,
            text="voice assistant",
            font=ctk.CTkFont(size=13),
            text_color=MUTED,
        ).pack(side="left", padx=(12, 0), pady=(16, 0))

        self.status_frame = ctk.CTkFrame(
            header, fg_color=PANEL, corner_radius=20, height=34
        )
        self.status_frame.pack(side="right")

        self.status_dot = ctk.CTkLabel(
            self.status_frame,
            text="●",
            font=ctk.CTkFont(size=16),
            text_color=AMBER,
        )
        self.status_dot.pack(side="left", padx=(14, 6), pady=6)

        self.status_label = ctk.CTkLabel(
            self.status_frame,
            text="STANDBY",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=AMBER,
        )
        self.status_label.pack(side="left", padx=(0, 14), pady=6)

    def _build_hero(self):
        self.hero = tk.Canvas(
            self,
            height=132,
            bg=BG,
            highlightthickness=0,
            bd=0,
        )
        self.hero.pack(fill="x", padx=26, pady=(2, 4))

    def _build_body(self):
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=26, pady=(0, 8))

        left = ctk.CTkFrame(main, fg_color=PANEL, corner_radius=18)
        left.pack(side="left", fill="both", expand=True)

        self.log_box = ctk.CTkTextbox(
            left,
            fg_color=PANEL,
            text_color=TEXT,
            font=ctk.CTkFont(family="Consolas", size=12),
            corner_radius=18,
            border_width=0,
            wrap="word",
        )
        self.log_box.pack(fill="both", expand=True, padx=16, pady=16)
        self.log_box.configure(state="disabled")

        right = ctk.CTkFrame(main, fg_color="transparent", width=216)
        right.pack(side="right", fill="y", padx=(16, 0))
        right.pack_propagate(False)

        ctk.CTkLabel(
            right,
            text="QUICK ACTIONS",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=MUTED,
        ).pack(anchor="w", pady=(0, 8))

        actions = [
            ("▶  YouTube", self.quick_youtube),
            ("💬  WhatsApp", self.quick_whatsapp),
            ("✉  Email", self.quick_email),
            ("🔒  Lock laptop", self.quick_lock),
            ("📸  Screenshot", self.quick_screenshot),
            ("⚙  Setup Email", self.quick_setup_email),
            ("👤  Add Contact", self.quick_add_contact),
            ("🖥  Open HUD", self.open_hud),
        ]
        for label, command in actions:
            ctk.CTkButton(
                right,
                text=label,
                command=command,
                fg_color=PANEL_2,
                hover_color="#1f2c3a",
                text_color=TEXT,
                corner_radius=12,
                height=36,
                anchor="w",
                font=ctk.CTkFont(size=13),
            ).pack(fill="x", pady=3)

    def _build_footer(self):
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=26, pady=(0, 18))

        self.start_btn = ctk.CTkButton(
            footer,
            text="Start Listening",
            command=self.start_listening,
            fg_color=ACCENT,
            hover_color="#00b8d4",
            text_color="#061018",
            corner_radius=12,
            height=42,
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self.start_btn.pack(side="left")

        self.stop_btn = ctk.CTkButton(
            footer,
            text="Stop",
            command=self.stop_listening,
            fg_color=RED,
            hover_color="#d63b55",
            text_color="#ffffff",
            corner_radius=12,
            height=42,
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self.stop_btn.pack(side="left", padx=8)

        ctk.CTkLabel(
            footer,
            text="Say 'Hello Matty' to activate",
            font=ctk.CTkFont(size=12),
            text_color=MUTED,
        ).pack(side="right")

    # ---------- animation ----------

    def _animate(self):
        """STEP 5 - animation tick, every 50 ms (~20 fps).

        STEP 1  advance the phase counter (drives the pulse/wave motion)
        STEP 2  redraw the reactor orb and the audio waveform
        STEP 3  when the estimated speech time is over, drop SPEAKING back to
                ACTIVE (session still open) or STANDBY
        STEP 4  reschedule itself - tkinter has no animation loop of its own
        """
        self.phase += 0.12  # STEP 1
        self._draw_hero()   # STEP 2
        if self.anim_state == "SPEAKING" and time.time() > self.speaking_until:
            self.set_status(
                "ACTIVE" if time.time() < self.active_until else "STANDBY"
            )
        self.after(50, self._animate)  # STEP 4

    def _draw_hero(self):
        c = self.hero
        c.delete("all")
        width = c.winfo_width()
        if width <= 1:
            width = 840
        height = int(c.cget("height"))
        cy = height // 2
        color = self.STATUS_COLORS.get(self.anim_state, ACCENT)

        # Reactor orb
        cx = 96
        pulse = 1.0 + 0.06 * math.sin(self.phase)
        for radius, ring in ((58, "#052a30"), (50, "#084650"), (43, "#0a6675")):
            r = radius * pulse
            c.create_oval(
                cx - r, cy - r, cx + r, cy + r,
                outline=ring, width=2,
            )

        r = 35 * pulse
        for i in range(8):
            a = self.phase * 0.8 + i * math.pi / 4
            c.create_line(
                cx + (r - 9) * math.cos(a),
                cy + (r - 9) * math.sin(a),
                cx + r * math.cos(a),
                cy + r * math.sin(a),
                fill=color,
                width=2,
            )

        c.create_oval(cx - 17, cy - 17, cx + 17, cy + 17, fill="#0b2a30", outline=color, width=2)
        c.create_oval(cx - 7, cy - 7, cx + 7, cy + 7, fill=color, outline="")

        # Waveform
        start = 220
        end = width - 20
        bars = 48
        step = max(4.0, (end - start) / bars)
        amp = {
            "STANDBY": 5,
            "ACTIVE": 24,
            "PROCESSING": 30,
            "SPEAKING": 34,
            "STOPPED": 2,
            "NO MIC": 0,
        }.get(self.anim_state, 5)

        # While listening, the wave height follows the REAL microphone level
        # (self.mic_level, 0-100) instead of a fixed animation amplitude. If the
        # bars stay flat while you talk, the microphone is not delivering audio.
        if self.anim_state in ("STANDBY", "ACTIVE"):
            amp = max(3, min(34, 3 + self.mic_level * 0.3))

        for i in range(bars):
            x = start + i * step
            val = math.sin(self.phase * 2.2 + i * 0.42) * math.cos(
                self.phase * 0.7 + i * 0.13
            )
            h = max(2, 4 + amp * abs(val))
            bar_color = color if i % 4 else GREEN
            c.create_line(
                x, cy - h, x, cy + h,
                fill=bar_color,
                width=max(2, step * 0.45),
                capstyle="round",
            )

    # ---------- state ----------

    def log(self, text, tag="sys"):
        """Append one line to the transcript (UI thread only)."""
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def set_status(self, status):
        """Change the status word + colour of the badge and the orb."""
        self.anim_state = status
        color = self.STATUS_COLORS.get(status, TEXT)
        self.status_label.configure(text=status, text_color=color)
        self.status_dot.configure(text_color=color)

    def start_listening(self):
        """STEP 2 - launch the voice loop as a daemon thread (once)."""
        if self.listening:
            return
        self.listening = True
        self.set_status("STANDBY")
        self.log("Listening started.", "sys")
        self.thread = threading.Thread(target=self.voice_loop, daemon=True)
        self.thread.start()

    def stop_listening(self):
        """Ask the voice loop to exit; it notices self.listening == False."""
        self.listening = False
        self.set_status("STOPPED")
        self.log("Listening stopped.", "sys")

    def open_hud(self):
        if os.path.exists(HUD_PATH):
            webbrowser.open("file:///" + HUD_PATH.replace("\\", "/"))
        else:
            self.log("HUD file not found: " + HUD_PATH, "sys")

    # ---------- quick actions ----------

    def quick_youtube(self):
        song = simpledialog.askstring("YouTube", "What song or video?", parent=self)
        if song:
            reply = matty_actions.try_action(f"play {song} on YouTube")
            if not reply:
                reply = f"Playing {song} on YouTube."
            self._say(reply)

    def quick_whatsapp(self):
        contact = simpledialog.askstring(
            "WhatsApp", "Contact name or phone number:", parent=self
        )
        if not contact:
            return
        message = simpledialog.askstring("WhatsApp", "Message:", parent=self)
        reply = matty_actions.send_whatsapp_message(
            contact, message or "Hello from Matty"
        )
        self._say(reply)

    def quick_email(self):
        address = simpledialog.askstring("Email", "Recipient email:", parent=self)
        if not address:
            return
        subject = simpledialog.askstring("Email", "Subject:", parent=self) or ""
        body = simpledialog.askstring("Email", "Message:", parent=self) or ""
        reply = matty_actions.send_email(address, subject, body)
        self._say(reply)

    def quick_lock(self):
        reply = matty_actions.try_action("lock my laptop")
        self._say(reply or "Locking your laptop.")

    def quick_screenshot(self):
        reply = matty_actions.try_action("take a screenshot")
        self._say(reply or "Opening the screenshot tool.")

    def quick_setup_email(self):
        address = simpledialog.askstring(
            "Setup Email", "Your Gmail address:", parent=self
        )
        if not address:
            return
        password = simpledialog.askstring(
            "Setup Email",
            "Gmail app password (16 characters):",
            parent=self,
            show="*",
        )
        if not password:
            return
        reply = matty_actions.setup_email(address, password)
        self._say(reply)

    def quick_add_contact(self):
        name = simpledialog.askstring(
            "Add Contact", "Contact name (for example John):", parent=self
        )
        if not name:
            return
        phone = simpledialog.askstring(
            "Add Contact",
            "Phone number with country code (for example +919876543210):",
            parent=self,
        )
        if not phone:
            return
        saved = matty_config.add_contact(name, phone)
        self._say(f"Saved {name} as {saved}.")

    def _say(self, text):
        self.log("Matty: " + text, "matty")
        self.set_status("SPEAKING")
        self.speaking_until = time.time() + max(2.0, len(text) * 0.055)
        speak(text)

    # ---------- voice loop ----------

    def voice_loop(self):
        """Background voice pipeline for the classic window.

        STEP 1  check the Groq key (must never block this thread)
        STEP 2  find and open a microphone that really works
        STEP 3  keep one audio stream open and listen for a phrase
        STEP 4  audio -> text, then wake word / session handling
        STEP 5  command -> matty_brain.think()
        STEP 6  reply -> speak()

        Every failure is written to the on-screen transcript AND stdout, so the
        console window always explains why nothing happened.
        """

        def trace(text, tag="sys"):
            print(f"[matty:{tag}] {text}", flush=True)
            self.events.put(("log", text, tag))

        # ---- STEP 1: cloud key (offline mode is allowed) -----------------
        if not ensure_api_key(interactive=False, notify=lambda msg: trace(msg)):
            trace("Offline mode: local actions still work, AI answers are limited.")

        # ---- STEP 2: recognizer settings ---------------------------------
        recognizer = _tuned_recognizer()

        # ---- STEP 3: microphone ------------------------------------------
        try:
            mic, name, rate = open_microphone()
            trace(f"Microphone ready: {name} @ {rate} Hz")
        except Exception as exc:
            trace(f"Microphone error: {exc}")
            self.events.put(("status", "NO MIC"))
            self.listening = False
            return

        # Keep the stream open for the whole session: re-opening it for every
        # phrase clipped the start of short wake words like "Hello Matty".
        try:
            source = mic.__enter__()
        except Exception as exc:
            trace(f"Microphone error: {exc}")
            self.events.put(("status", "NO MIC"))
            self.listening = False
            return

        try:
            try:
                recognizer.adjust_for_ambient_noise(source, duration=1.0)
            except Exception as exc:
                trace(f"Noise calibration skipped: {exc}")

            self.events.put(("status", "STANDBY"))
            trace(f"Listening (threshold {int(recognizer.energy_threshold)}). Say 'Hello Matty'.")
            silence_streak = 0

            # Barge-in threshold: loud enough that Matty's own speaker output
            # does not trigger it, quiet enough for a normal voice.
            barge_threshold = max(1200, int(recognizer.energy_threshold * 3))
            last_level_push = [0.0]

            def on_level(rms):
                """Send the live mic level to the UI (throttled to ~10/s)."""
                now = time.time()
                if now - last_level_push[0] < 0.1:
                    return
                last_level_push[0] = now
                self.events.put(("level", min(100, int((max(0, rms) ** 0.5) * 2))))

            while self.listening:
                try:
                    # ---- STEP 3b: half-duplex gate -----------------------
                    # Never record while Matty is speaking; if the user talks
                    # over it, stop talking and listen instead.
                    if SPEECH_ACTIVE.is_set():
                        # Two consecutive loud windows (~280 ms) are required, so
                        # a single click cannot cut Matty off mid-sentence.
                        if (
                            BARGE_IN
                            and user_is_talking(source, barge_threshold)
                            and user_is_talking(source, barge_threshold)
                        ):
                            stop_speaking()
                            trace("Interrupted - listening to you.")
                            flush_stream(source, 0.15)
                        else:
                            time.sleep(0.05)
                            continue

                    # ---- STEP 3 (cont.): one spoken phrase ----------------
                    with tap_levels(source, on_level):
                        audio = recognizer.listen(source, timeout=8, phrase_time_limit=7)

                    # Pure digital silence means the OS is muting us, not that
                    # the user is quiet.
                    if audio_level(audio) == 0:
                        silence_streak += 1
                        if silence_streak == 3:
                            trace(
                                "Microphone is delivering silence. Open Settings > "
                                "Privacy & security > Microphone and allow desktop apps."
                            )
                    else:
                        silence_streak = 0

                    # ---- STEP 4: audio -> text ---------------------------
                    query, language = recognize_detailed(recognizer, audio)
                    query = query.strip()
                    tag = f"  [{language}]" if language and not language.lower().startswith("en") else ""
                    self.events.put(("log", f"You: {query}{tag}", "you"))

                    # ---- STEP 4 (cont.): wake word + session -------------
                    command, woken = extract_wake(query)
                    now = time.time()

                    if woken:
                        self.active_until = now + SESSION_SECONDS
                        self.events.put(("status", "ACTIVE"))
                        if not command:
                            self.events.put(
                                ("speak", "Yes, I'm here. What would you like me to do?")
                            )
                            continue
                    elif now > self.active_until:
                        self.events.put(("status", "STANDBY"))
                        continue
                    else:
                        self.active_until = now + SESSION_SECONDS

                    if not command:
                        continue

                    # ---- STEP 5 + 6: think, then speak -------------------
                    self.events.put(("status", "PROCESSING"))
                    reply = matty_brain.think(command)
                    self.events.put(("log", f"Matty: {reply}", "matty"))
                    self.events.put(
                        ("status", "ACTIVE" if time.time() < self.active_until else "STANDBY")
                    )
                    self.events.put(("speak", reply))
                    # Drop the tail of our own voice before listening again.
                    flush_stream(source)

                except sr.WaitTimeoutError:
                    if time.time() > self.active_until:
                        self.events.put(("status", "STANDBY"))
                except sr.UnknownValueError:
                    continue
                except SpeechUnavailable as exc:
                    trace(f"Speech-to-text unavailable: {exc}")
                    time.sleep(1.0)
                except Exception as exc:
                    trace(f"Voice loop notice: {exc}")
                    time.sleep(0.3)
        finally:
            try:
                mic.__exit__(None, None, None)
            except Exception:
                pass

    def poll_events(self):
        """STEP 4 - apply everything the voice thread posted, then reschedule.

        Runs on the UI thread every 100 ms, so it is the ONLY place that is
        allowed to touch widgets. Three message kinds exist:
            ("log", text, tag)   -> append a transcript line
            ("status", word)     -> change the status badge / orb colour
            ("speak", text)      -> show SPEAKING and queue the sentence
        """
        try:
            while True:  # drain everything that is waiting, then stop
                kind, *rest = self.events.get_nowait()
                if kind == "log":
                    text, tag = rest
                    self.log(text, tag)
                elif kind == "status":
                    self.set_status(rest[0])
                elif kind == "speak":
                    text = rest[0]
                    self.set_status("SPEAKING")
                    # Estimate how long the sentence takes, so the orb returns
                    # to ACTIVE/STANDBY at roughly the right moment.
                    self.speaking_until = time.time() + max(2.0, len(text) * 0.055)
                    speak(text)
                elif kind == "level":
                    # Live microphone loudness from the voice thread.
                    self.mic_level = rest[0]
        except queue.Empty:
            pass

        # Reschedule: this is what keeps the pump alive.
        self.after(100, self.poll_events)

    def on_close(self):
        """Stop the voice loop and close the window."""
        self.listening = False
        self.destroy()


def main():
    """Entry point: dark theme, build the window, run the tkinter loop."""
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    app = MattyUI()
    app.mainloop()


if __name__ == "__main__":
    main()
