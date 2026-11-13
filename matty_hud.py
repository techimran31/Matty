"""
matty_hud.py - Holographic JARVIS-style desktop HUD for Matty.

Uses pywebview to render matty_hud.html inside a desktop window. The voice
loop runs in a background thread and pushes status, transcript and vitals
updates into the page through JavaScript.
"""

import json
import os
import queue
import threading
import time

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
    recognize,
    safe_print,
    recognize_detailed,
    register_stop_hook,
    stop_speaking,
    tap_levels,
    user_is_talking,
    _tuned_recognizer,
)

APP_DIR = os.path.dirname(os.path.abspath(__file__))
HUD_PATH = os.path.join(APP_DIR, "matty_hud.html")

runtime = {"active_until": 0.0}

# ---------------------------------------------------------------------------
# Speech output (Windows SAPI with pyttsx3 fallback)
# ---------------------------------------------------------------------------
# WHY A QUEUE + THREAD:
#   Speaking blocks for as long as the sentence takes. If the voice loop spoke
#   directly, the microphone would be deaf during that time and the HUD would
#   freeze. So replies go into a queue and one worker thread does the talking.
#
#   SAPI (win32com) is used on Windows because it is reliable from a background
#   thread; pyttsx3 is the cross-platform fallback.

_tts_queue = queue.Queue()
_tts_thread = None
_tts_lock = threading.Lock()


def _tts_worker():
    """Own the text-to-speech engine for the whole process lifetime.

    STEP 1  initialise COM on THIS thread (SAPI objects are thread-bound)
    STEP 2  create the voice once (creating it per sentence is slow)
    STEP 3  register the barge-in hook, so stop_speaking() can cut us off
    STEP 4  loop forever: take a sentence, speak it, mark it done

    SPEECH_ACTIVE is set for exactly as long as audio is coming out of the
    speakers. The voice loop uses it to stay deaf while Matty talks.
    """
    # STEP 1 - COM apartment for this thread
    try:
        import pythoncom

        pythoncom.CoInitialize()
    except Exception:
        pass

    # STEP 2 - one reusable voice object
    voice = None
    try:
        import win32com.client

        voice = win32com.client.Dispatch("SAPI.SpVoice")
    except Exception:
        voice = None

    # STEP 3 - how to silence this engine instantly
    def _silence():
        # Drop everything still waiting to be spoken.
        while not _tts_queue.empty():
            try:
                _tts_queue.get_nowait()
                _tts_queue.task_done()
            except queue.Empty:
                break
        try:
            if voice is not None:
                # SAPI flag 3 = asynchronous + purge the current utterance.
                voice.Speak("", 3)
        except Exception:
            pass

    register_stop_hook(_silence)

    # STEP 4 - speak whatever arrives in the queue
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
    """Queue a sentence for speech, starting the worker thread on first use."""
    global _tts_thread
    if not text:
        return
    with _tts_lock:
        if _tts_thread is None or not _tts_thread.is_alive():
            _tts_thread = threading.Thread(target=_tts_worker, daemon=True)
            _tts_thread.start()
    _tts_queue.put(text)


# ---------------------------------------------------------------------------
# HUD bridge helpers - how Python talks to the web page
# ---------------------------------------------------------------------------
# The page defines three globals: setMattyState(state, text), addMattyLog(role,
# text) and setVitals(cpu, ram, disk, battery). We call them with evaluate_js.
# json.dumps() is used for every argument so quotes and newlines inside a reply
# can never break the generated JavaScript.

_js_warned = False


def _js(window, script):
    """Push a JavaScript call into the HUD page.

    Failures are normal for the first milliseconds (the page is still loading),
    so they are swallowed - but the very first one is printed once, because a
    silent failure here used to make the HUD look frozen with no explanation.
    """
    global _js_warned
    try:
        window.evaluate_js(script)
    except Exception as exc:
        if not _js_warned:
            _js_warned = True
            print(f"[hud] evaluate_js failed once: {exc}", flush=True)


def set_state(window, state, text=""):
    """Change the big status word: STANDBY / ACTIVE / PROCESSING / SPEAKING."""
    _js(
        window,
        f"window.setMattyState({json.dumps(state)}, {json.dumps(text)});",
    )


def log(window, role, text):
    """Append one line to the transcript. role = you | matty | sys."""
    _js(
        window,
        f"window.addMattyLog({json.dumps(role)}, {json.dumps(text)});",
    )


def revert_state(window):
    """After speaking, go back to ACTIVE (session open) or STANDBY."""
    set_state(
        window,
        "ACTIVE" if time.time() < runtime["active_until"] else "STANDBY",
    )


def set_mic_level(window, rms):
    """Push the live microphone loudness (0-100) into the HUD meter.

    This is the honest answer to "is it listening?": the bar only moves when
    the microphone is actually delivering audio.
    """
    percent = min(100, int((max(0, rms) ** 0.5) * 2))
    _js(window, f"window.setMicLevel({percent});")


def say(window, text):
    """Log the reply, show SPEAKING, speak it, then restore the status.

    The status is restored with a timer instead of waiting for SAPI, because
    SAPI gives no reliable "finished speaking" callback from another thread.
    ~55 ms per character is a good estimate of how long speech takes.
    """
    log(window, "matty", text)
    set_state(window, "SPEAKING")
    speak(text)
    threading.Timer(max(2.0, len(text) * 0.055), lambda: revert_state(window)).start()


# ---------------------------------------------------------------------------
# JavaScript API - what the page's buttons call
# ---------------------------------------------------------------------------
# pywebview exposes this object as window.pywebview.api in the page, so a click
# in the HUD becomes a normal Python call whose return value is printed into
# the transcript by matty_hud.html.


class Api:
    """Bridge between the HUD buttons and the local action layer.

    IMPORTANT: every attribute here must start with an underscore.
    pywebview builds window.pywebview.api by walking ALL public attributes of
    this object recursively (webview/util.py: get_functions). A public
    `self.window` therefore made pywebview crawl the native WinForms window
    (window.native.AccessibilityObject.Bounds.Empty.Empty...) until it hit
    "maximum recursion depth exceeded" - which froze the UI thread and, with
    it, every evaluate_js call from the voice loop. Private names are skipped.
    """

    def __init__(self):
        self._window = None

    def _set_window(self, window):
        self._window = window

    def run_action(self, kind, args=None):
        """Execute one UI action and return the sentence to display.

        kind is the short string chosen by the button:
            youtube      -> play <query> on YouTube
            whatsapp     -> send a WhatsApp message
            email        -> send an email
            lock         -> lock the screen
            screenshot   -> open the snipping tool
            setup_email  -> store address + app password
            add_contact  -> save name -> phone number
            command      -> typed text goes to the AI brain

        Errors are returned as text instead of raised: an exception here would
        only surface as an unhelpful JS promise rejection.
        """
        args = args or {}
        try:
            if kind == "youtube":
                query = args.get("query", "")
                return matty_actions.try_action(f"play {query} on YouTube")
            if kind == "whatsapp":
                return matty_actions.send_whatsapp_message(
                    args.get("contact", ""), args.get("message", "")
                )
            if kind == "email":
                return matty_actions.send_email(
                    args.get("to", ""),
                    args.get("subject", ""),
                    args.get("body", ""),
                )
            if kind == "lock":
                return matty_actions.try_action("lock my laptop")
            if kind == "screenshot":
                return matty_actions.try_action("take a screenshot")
            if kind == "setup_email":
                return matty_actions.setup_email(
                    args.get("email", ""), args.get("password", "")
                )
            if kind == "add_contact":
                saved = matty_config.add_contact(
                    args.get("name", ""), args.get("phone", "")
                )
                return f"Saved {args.get('name')} as {saved}."
            if kind == "command":
                return matty_brain.think(args.get("text", ""))
            if kind == "test_mic":
                return self._test_mic()
            if kind == "set_key":
                # Save the Groq key from the HUD, then refresh the footer badge.
                message = matty_brain.save_api_key(args.get("key", ""))
                self._push_cloud_status()
                return message
            if kind == "cloud_status":
                return self._cloud_text()
            if kind == "test_cloud":
                # One real API call, so the exact failure is visible.
                message = matty_brain.cloud_test()
                self._push_cloud_status()
                return message
            if kind == "activate":
                # Open a fresh 2 minute session without needing the wake word.
                return self._activate()
            if kind == "session":
                return self._session_text()
            return "Unknown action."
        except Exception as e:
            return f"Action failed: {e}"

    def _activate(self):
        """Open a 2 minute listening session from a button click."""
        runtime["active_until"] = time.time() + SESSION_SECONDS
        set_state(self._window, "ACTIVE")
        return f"Listening for {SESSION_SECONDS} seconds - just talk."

    def _session_text(self):
        """How long the current wake session still has to run."""
        left = int(runtime["active_until"] - time.time())
        if left <= 0:
            return "Session closed. Say 'Hello Matty' or click ACTIVATE."
        return f"Session open for another {left}s."

    def _cloud_text(self):
        """Human readable cloud state for the transcript."""
        status = matty_brain.cloud_status()
        if not status["has_key"]:
            return "Cloud: OFFLINE (no Groq API key). Click SET KEY to add one."
        if status["cooldown"]:
            return f"Cloud: rate limited for {status['cooldown']}s."
        return "Cloud: ONLINE."
    def _push_cloud_status(self):
        """Update the ONLINE / OFFLINE badge in the footer."""
        if self._window is None:
            return
        status = matty_brain.cloud_status()
        _js(self._window, f"window.setCloudStatus({json.dumps(status['ready'])});")

    def _test_mic(self):
        """Record 3 seconds and report what the microphone actually heard.

        This is the "is it listening?" button. It answers three questions in
        one line: did the device open, was there any sound, and what words were
        recognised.
        """
        import speech_recognition as sr

        try:
            mic, name, rate = open_microphone()
        except Exception as exc:
            return f"Microphone error: {exc}"

        recognizer = _tuned_recognizer()
        try:
            with mic as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.6)
                audio = recognizer.listen(source, timeout=4, phrase_time_limit=3)
        except sr.WaitTimeoutError:
            return f"{name}: no sound at all in 4 seconds. Is the mic muted?"
        except Exception as exc:
            return f"Microphone error: {exc}"

        level = audio_level(audio)
        if level == 0:
            return (
                f"{name}: pure silence. Allow desktop apps to use the microphone "
                "in Settings > Privacy & security > Microphone."
            )

        try:
            text = recognize(recognizer, audio)
        except sr.UnknownValueError:
            return f"{name}: heard you (level {level}) but no words were recognised."
        except SpeechUnavailable as exc:
            return f"{name}: heard you (level {level}) but speech-to-text failed: {exc}"
        return f'{name}: level {level}, heard "{text}".'


# ---------------------------------------------------------------------------
# Background loops
# ---------------------------------------------------------------------------


def voice_loop(window):
    """Background voice pipeline for the HUD.

    STEP 1  check the Groq key (never blocks this thread)
    STEP 2  find and open a microphone that really works
    STEP 3  keep that stream open and listen for one phrase
    STEP 4  audio -> text, then detect the wake word / session
    STEP 5  hand the command to matty_brain.think()
    STEP 6  speak the reply and go back to listening

    Every step reports to BOTH the HUD transcript and the console, so a
    failure can never be invisible again.
    """
    import speech_recognition as sr

    def trace(role, text):
        """Mirror one message into the console and the HUD transcript."""
        safe_print(f"[matty:{role}] {text}")
        log(window, role, text)

    # ---- STEP 1: cloud key (offline mode is fine, it must not block) -----
    if not ensure_api_key(interactive=False, notify=lambda msg: trace("sys", msg)):
        trace("sys", "Offline mode: local actions still work, AI answers are limited.")

    # Tell the footer badge the truth: ONLINE only when a key exists and the
    # model is not cooling down.
    status = matty_brain.cloud_status()
    _js(window, f"window.setCloudStatus({json.dumps(status['ready'])});")
    if not status["has_key"]:
        trace("sys", "No Groq API key found - click SET KEY to enable AI answers.")

    # ---- STEP 2: recognizer settings ------------------------------------
    recognizer = _tuned_recognizer()

    # ---- STEP 3: microphone ---------------------------------------------
    mic = None
    while mic is None:
        try:
            mic, name, rate = open_microphone()
            trace("sys", f"Microphone ready: {name} @ {rate} Hz")
        except Exception as exc:
            set_state(window, "NO MIC")
            trace("sys", f"Microphone error: {exc}")
            trace("sys", "Retrying in 5s. Allow microphone access for desktop apps.")
            time.sleep(5)

    # Open the audio stream ONCE and keep it open for the whole session.
    # The old code used `with mic as source` inside the loop, which opened and
    # closed the WASAPI stream for every phrase; the first ~0.5s of speech was
    # lost each time, so short wake words like "Hello Matty" were clipped and
    # never recognised.
    source = mic.__enter__()
    try:
        # Learn the room noise level so the silence threshold fits this mic.
        try:
            recognizer.adjust_for_ambient_noise(source, duration=1.0)
        except Exception as exc:
            trace("sys", f"Noise calibration skipped: {exc}")

        set_state(window, "STANDBY")
        trace(
            "sys",
            f"Listening (threshold {int(recognizer.energy_threshold)}). "
            "Say 'Hello Matty'.",
        )
        silence_streak = 0

        # Barge-in threshold: loud enough that Matty's own speaker output does
        # not trigger it, quiet enough that a normal voice does.
        barge_threshold = max(1200, int(recognizer.energy_threshold * 3))

        # Throttle the level meter to ~10 updates per second; evaluate_js is
        # not free and the meter does not need 40 fps.
        last_level_push = [0.0]

        # Throttle the "I ignored that" hint so it informs without flooding.
        last_ignore_hint = [0.0]

        def on_level(rms):
            now = time.time()
            if now - last_level_push[0] < 0.1:
                return
            last_level_push[0] = now
            set_mic_level(window, rms)

        while True:
            try:
                # ---- STEP 3b: half-duplex gate --------------------------
                # While Matty is speaking, do not record. Instead watch the
                # microphone for a loud, sustained voice: that is the user
                # interrupting, and the user always wins.
                if SPEECH_ACTIVE.is_set():
                    # Two consecutive loud windows (~280 ms) are required, so a
                    # single click or a loud consonant cannot cut Matty off.
                    if (
                        BARGE_IN
                        and user_is_talking(source, barge_threshold)
                        and user_is_talking(source, barge_threshold)
                    ):
                        stop_speaking()
                        trace("sys", "Interrupted - listening to you.")
                        flush_stream(source, 0.15)
                    else:
                        time.sleep(0.05)
                        continue

                # ---- STEP 3 (cont.): wait for one spoken phrase ----------
                # tap_levels reports the real loudness of every chunk, which
                # is what drives the MIC meter in the HUD.
                with tap_levels(source, on_level):
                    audio = recognizer.listen(source, timeout=8, phrase_time_limit=7)

                # A dead/blocked microphone returns pure digital silence.
                # Three silent phrases in a row is a permission problem, not
                # a user who is quiet, so say it out loud.
                if audio_level(audio) == 0:
                    silence_streak += 1
                    if silence_streak == 3:
                        trace(
                            "sys",
                            "Microphone is delivering silence. Open Settings > "
                            "Privacy & security > Microphone and allow desktop apps.",
                        )
                else:
                    silence_streak = 0

                # ---- STEP 4: audio -> text (any language) ----------------
                query, language = recognize_detailed(recognizer, audio)
                query = query.strip()
                # Show the detected language when it is not English, so you can
                # see that a Hindi/Spanish/Arabic phrase was understood.
                tag = f"  [{language}]" if language and not language.lower().startswith("en") else ""
                log(window, "you", query + tag)

                # ---- STEP 4 (cont.): wake word + 2 minute session -------
                command, woken = extract_wake(query)
                now = time.time()

                if woken:
                    runtime["active_until"] = now + SESSION_SECONDS
                    set_state(window, "ACTIVE")
                    if not command:
                        say(window, "Yes, I'm here. What would you like me to do?")
                        continue
                elif now > runtime["active_until"]:
                    # The 2 minute wake session has expired. This used to happen
                    # silently, so the user saw their words in the transcript
                    # and got no answer, and concluded Matty was broken.
                    set_state(window, "STANDBY")
                    if now - last_ignore_hint[0] > 15:
                        last_ignore_hint[0] = now
                        trace(
                            "sys",
                            'Ignored - say "Hello Matty" or click ACTIVATE to wake me.',
                        )
                    continue
                else:
                    # Still inside the session: extend it on every command.
                    runtime["active_until"] = now + SESSION_SECONDS

                if not command:
                    continue

                # ---- STEP 5 + 6: think, then speak ----------------------
                set_state(window, "PROCESSING")
                reply = matty_brain.think(command)
                say(window, reply)

                # Drop the tail of our own voice so the next listen() starts
                # with the user, not with the end of the previous sentence.
                flush_stream(source)

            except sr.WaitTimeoutError:
                # Nobody spoke in time - that is not an error.
                if time.time() > runtime["active_until"]:
                    set_state(window, "STANDBY")
            except sr.UnknownValueError:
                # Speech detected but no understandable words.
                continue
            except SpeechUnavailable as exc:
                # Both recognisers failed technically (offline / blocked / 429).
                trace("sys", f"Speech-to-text unavailable: {exc}")
                time.sleep(1.0)
            except Exception as exc:
                trace("sys", f"Voice loop notice: {exc}")
                time.sleep(0.5)
    finally:
        # Always release the device so the next launch can grab it again.
        try:
            mic.__exit__(None, None, None)
        except Exception:
            pass


def vitals_loop(window):
    """Feed the HUD's system meters (CPU, RAM, disk, battery) every 2 seconds.

    STEP 1  read the four values with psutil
    STEP 2  battery is optional on desktops, so it is sent as JS null
    STEP 3  push one setVitals() call into the page
    STEP 4  sleep and repeat - a 1 s sampling window keeps CPU% meaningful
    """
    try:
        import psutil
    except Exception:
        return  # psutil missing: the HUD keeps its simulated meters

    while True:
        try:
            # STEP 1 + 2 - sample the machine
            cpu = int(psutil.cpu_percent(interval=1))
            ram = int(psutil.virtual_memory().percent)
            disk = int(psutil.disk_usage(os.path.abspath(os.sep)).percent)
            try:
                batt = int(psutil.sensors_battery().percent)
            except Exception:
                batt = None
            batt_js = "null" if batt is None else str(batt)

            # STEP 3 - push into the page
            _js(window, f"window.setVitals({cpu}, {ram}, {disk}, {batt_js});")
        except Exception:
            pass

        # STEP 4 - refresh twice per second pair
        time.sleep(2)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    """Start the HUD window and its two background threads.

    STEP 1  create the pywebview window and hand it the Api bridge
    STEP 2  start the voice loop + vitals loop as daemon threads
    STEP 3  hand control to the GUI loop (this call blocks until the window
            is closed, and it MUST run on the main thread)
    """
    import webview

    # STEP 1 - the window and its JS bridge
    api = Api()
    window = webview.create_window(
        "MATTY · Holographic HUD",
        HUD_PATH,
        js_api=api,
        width=1360,
        height=820,
        min_size=(1100, 700),
        background_color="#041018",
    )
    api._set_window(window)

    # STEP 2 - background workers (daemon: they die with the window)
    def start_background(_window):
        threading.Thread(target=voice_loop, args=(_window,), daemon=True).start()
        threading.Thread(target=vitals_loop, args=(_window,), daemon=True).start()

    # STEP 3 - run the GUI loop on the main thread
    webview.start(start_background, window)


if __name__ == "__main__":
    main()
