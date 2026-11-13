"""
matty_voice.py - Microphone, speech recognition and speech output for Matty.

HOW TO READ THIS FILE
---------------------
The voice pipeline always runs in this order:

    STEP 1  make PyAudio importable
    STEP 2  microphone discovery + safe opening        (open_microphone)
    STEP 3  audio bytes  ->  text                      (recognize)
    STEP 4  text         ->  (command, woke?)          (extract_wake)
    STEP 5  command      ->  Matty reply               (matty_brain.think)
    STEP 6  reply        ->  spoken audio              (speak)

matty_hud.py and matty_ui.py both import the helpers below, so a fix in this
file fixes the HUD *and* the classic window at the same time.
"""

import os
import subprocess
import sys
import threading
import time

# ---------------------------------------------------------------------------
# STEP 1 - Make a working "pyaudio" module available.
# ---------------------------------------------------------------------------
# speech_recognition needs the PyAudio C extension to touch the microphone.
# There is no official PyAudio wheel for Python 3.14 on Windows, so
# requirements.txt installs PyAudioWPatch, which is a drop-in replacement.
# speech_recognition does `import pyaudio` at runtime, so we register
# PyAudioWPatch under that name inside sys.modules. This MUST happen before
# the first sr.Microphone() call, which is why it sits at the top of the file.
try:
    # Pylance reports "Import pyaudio could not be resolved" because only
    # PyAudioWPatch is installed - the alias is created at runtime, which static
    # analysis cannot see. The warning is silenced here; the except branch below
    # is the real fallback, so nothing can break at runtime.
    import pyaudio  # type: ignore  # noqa: F401  (real PyAudio, if installed)
except ImportError:
    try:
        import pyaudiowpatch as pyaudio

        sys.modules["pyaudio"] = pyaudio
    except ImportError:
        pyaudio = None  # open_microphone() will report this clearly

import speech_recognition as sr

import matty_brain
import matty_config

# ---------------------------------------------------------------------------
# STEP 0 - make console output safe for every language
# ---------------------------------------------------------------------------
# Windows consoles often use cp1252, which cannot encode ₹, Hindi, Arabic or
# Chinese. A single print() of such a reply would raise UnicodeEncodeError and
# kill the voice thread. errors="replace" turns unprintable characters into
# '?' instead of crashing.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass


def safe_print(text):
    """print() that never raises on encoding problems."""
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(str(text).encode(encoding, "replace").decode(encoding, "replace"), flush=True)

# ---------------------------------------------------------------------------
# Constants shared with the UI layers
# ---------------------------------------------------------------------------
# After "Hello Matty", the assistant stays awake this many seconds so the user
# can give several commands without repeating the wake word.
SESSION_SECONDS = 120

# Phrases that wake Matty up, in several languages. The name itself is the
# strongest signal, so a bare wake word anywhere in the sentence also works.
WAKE_PHRASES = (
    "hello matty",
    "hello maddy",
    "hello mattie",
    "hello madi",
    "hello marty",
    "hello mati",
    "hello matey",
    "hello madam",
    "hey matty",
    "hey maddy",
    "hey mattie",
    "hey madi",
    "hey marty",
    "hey mati",
    "hi matty",
    "hi maddy",
    "hi mattie",
    "ok matty",
    "okay matty",
    # Hindi / Urdu / Bengali
    "namaste matty",
    "namaskar matty",
    "hello matty ji",
    "matty suno",
    "suno matty",
    "arre matty",
    # Spanish / Portuguese / Italian / French / German
    "hola matty",
    "ola matty",
    "ola mati",
    "ciao matty",
    "bonjour matty",
    "salut matty",
    "hallo matty",
    "guten tag matty",
    # Russian / Arabic / Turkish / Indonesian
    "privet matty",
    "marhaba matty",
    "merhaba matty",
    "halo matty",
    # East Asian
    "ni hao matty",
    "konnichiwa matty",
    "annyeong matty",
)
WAKE_WORDS = ("matty", "maddy", "mattie", "madi", "marty", "mati")

# Language handling. "auto" lets Whisper detect the spoken language by itself,
# so Matty understands any language. Set MATTY_LANG=hi-IN (etc.) to force one.
DEFAULT_LANGUAGE = os.environ.get("MATTY_LANG", "auto")

# Filled in by recognize(): the language of the last phrase that was heard.
LAST_LANGUAGE = ""

# ---------------------------------------------------------------------------
# STEP 3b - half-duplex speech gate
# ---------------------------------------------------------------------------
# Matty must never listen to its own voice. While a sentence is being spoken
# SPEECH_ACTIVE is set, and the voice loop refuses to record. That single flag
# removes the whole class of bugs where Matty transcribes its own reply and
# then "executes" it as a command.
#
# Barge-in works the other way round: if the user starts talking while Matty is
# speaking, stop_speaking() purges the queue and silences SAPI immediately, so
# the user's command always wins. Disable with MATTY_BARGE_IN=0.
SPEECH_ACTIVE = threading.Event()
BARGE_IN = os.environ.get("MATTY_BARGE_IN", "1") not in ("0", "false", "no")

_stop_hooks = []


def register_stop_hook(fn):
    """Register a callback that silences the current text-to-speech engine."""
    if fn not in _stop_hooks:
        _stop_hooks.append(fn)


def stop_speaking():
    """Cut Matty off mid-sentence (used for barge-in and on shutdown)."""
    for hook in list(_stop_hooks):
        try:
            hook()
        except Exception:
            pass
    SPEECH_ACTIVE.clear()


class SpeechUnavailable(RuntimeError):
    """Raised when every speech-to-text engine failed for a technical reason
    (no internet, blocked API, missing key). Different from UnknownValueError,
    which only means 'the audio contained no understandable words'."""


# ---------------------------------------------------------------------------
# STEP 2 - Microphone discovery and safe opening
# ---------------------------------------------------------------------------


def pyaudio_module():
    """Return the PyAudio module, or None when no binding is installed."""
    if pyaudio is not None:
        return pyaudio
    try:
        import pyaudiowpatch as patch

        sys.modules["pyaudio"] = patch
        return patch
    except Exception:
        return None


def list_input_devices():
    """Return a list of dicts describing every device that can record audio.

    Loopback devices are marked, because on Windows the speaker loopback is
    listed as an 'input' device but records system sound, not the user's voice.
    """
    pa = pyaudio_module()
    if pa is None:
        return []

    devices = []
    audio = pa.PyAudio()
    try:
        for index in range(audio.get_device_count()):
            try:
                info = audio.get_device_info_by_index(index)
            except Exception:
                continue
            if int(info.get("maxInputChannels") or 0) <= 0:
                continue
            devices.append(
                {
                    "index": index,
                    "name": str(info.get("name") or f"device {index}"),
                    "channels": int(info.get("maxInputChannels") or 0),
                    "rate": int(info.get("defaultSampleRate") or 0),
                    "loopback": bool(info.get("isLoopbackDevice", False)),
                }
            )
    finally:
        try:
            audio.terminate()
        except Exception:
            pass
    return devices


def open_microphone(preferred_name=None):
    """Find a microphone that actually opens, and return (mic, name, rate).

    Why this exists: sr.Microphone() only trusts the *system default* device.
    On Windows that default is sometimes a disabled, virtual or loopback
    device, and then Matty records perfect silence while looking healthy.
    So we try the default first, then every real capture device, and we keep
    the first one whose stream opens successfully.

    Raises RuntimeError with a readable message if nothing can be opened.
    """
    devices = list_input_devices()

    # Build the candidate order: named preference, then system default, then
    # every real (non-loopback) capture device.
    candidates = []
    if preferred_name:
        needle = preferred_name.lower()
        for dev in devices:
            if not dev["loopback"] and needle in dev["name"].lower():
                candidates.append(dev["index"])
    candidates.append(None)  # None = "whatever Windows says is the default"
    for dev in devices:
        if not dev["loopback"] and dev["index"] not in candidates:
            candidates.append(dev["index"])

    failures = []
    for index in candidates:
        try:
            # Build a throwaway instance and open it once: that is the only
            # reliable way to prove the device is present, enabled and not
            # locked by another app (Teams/Zoom/OBS often hold the mic).
            probe = sr.Microphone(device_index=index)
            with probe as source:  # noqa: F841 - opening it is the test
                pass
            name = _device_name(devices, index, probe)
            # Return a FRESH instance that has never been opened, so the caller
            # can enter it exactly once and keep the stream open.
            return sr.Microphone(device_index=index), name, probe.SAMPLE_RATE
        except Exception as exc:
            failures.append(f"device {index}: {exc}")

    raise RuntimeError(
        "No usable microphone found. "
        + " | ".join(failures[:3])
        + " | Fix: Settings > Privacy & security > Microphone > let desktop apps "
        "access the microphone, and close apps that may hold the mic."
    )


def _device_name(devices, index, mic):
    """Best-effort human readable name for the chosen microphone."""
    if index is not None:
        for dev in devices:
            if dev["index"] == index:
                return dev["name"]
    try:
        pa = pyaudio_module()
        audio = pa.PyAudio()
        try:
            return str(audio.get_default_input_device_info().get("name"))
        finally:
            audio.terminate()
    except Exception:
        return f"system default ({getattr(mic, 'device_index', None)})"


# ---------------------------------------------------------------------------
# STEP 3 - Audio bytes -> text
# ---------------------------------------------------------------------------


def _groq_transcribe(audio, language):
    """Transcribe with Groq Whisper using the same free key as the brain.

    Whisper is multilingual. When language is "auto" the parameter is omitted,
    so Whisper detects the language itself and reports it back - that is what
    makes Matty work in every spoken language without configuration.

    Returns (text, detected_language) or (None, "") when no key is configured.
    """
    key = matty_brain._get_api_key()
    if not key:
        return None, ""

    from openai import OpenAI

    client = OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1")
    # audio.get_wav_data() gives 16-bit PCM WAV, which Whisper accepts directly.
    wav = audio.get_wav_data()

    kwargs = {}
    if language and str(language).lower() != "auto":
        kwargs["language"] = str(language).split("-")[0]

    response = client.audio.transcriptions.create(
        model="whisper-large-v3-turbo",
        file=("speech.wav", wav, "audio/wav"),
        **kwargs,
    )
    text = getattr(response, "text", None) or (response if isinstance(response, str) else "")
    detected = getattr(response, "language", None) or ""
    return (text.strip() or None), detected


def recognize(recognizer, audio, language=None):
    """Turn one recorded phrase into text, in any language.

    Order:
      1. Groq Whisper  - auto-detects the language, very accurate
      2. Google Web Speech - fallback, needs a concrete language code

    Raises sr.UnknownValueError  -> audio had no understandable words (normal)
    Raises SpeechUnavailable     -> both engines failed technically
    """
    return recognize_detailed(recognizer, audio, language)[0]


def recognize_detailed(recognizer, audio, language=None):
    """Same as recognize(), but returns (text, detected_language)."""
    global LAST_LANGUAGE

    language = language or DEFAULT_LANGUAGE
    problems = []
    heard_nothing = True

    # --- Engine 1: Groq Whisper (multilingual, auto-detects) --------------
    try:
        text, detected = _groq_transcribe(audio, language)
        if text:
            LAST_LANGUAGE = detected or ("" if str(language).lower() == "auto" else language)
            return text, LAST_LANGUAGE
    except Exception as exc:  # no key, no internet, 429, quota, ...
        heard_nothing = False
        problems.append(f"whisper: {type(exc).__name__}: {exc}")

    # --- Engine 2: Google Web Speech (needs a concrete language) ----------
    google_language = "en-US" if str(language).lower() == "auto" else language
    try:
        text = recognizer.recognize_google(audio, language=google_language)
        if text and text.strip():
            LAST_LANGUAGE = google_language
            return text.strip(), google_language
    except sr.UnknownValueError:
        pass  # silence / mumbling: not a technical failure
    except sr.RequestError as exc:
        heard_nothing = False
        problems.append(f"google: {exc}")

    if heard_nothing:
        raise sr.UnknownValueError()
    raise SpeechUnavailable("; ".join(problems))


def audio_level(audio):
    """Return the RMS loudness of a recorded phrase (0 = pure digital silence).

    Used to tell "the user said nothing" apart from "Windows is feeding us
    silence because microphone permission is denied".
    """
    try:
        import audioop

        return audioop.rms(audio.get_raw_data(), audio.sample_width)
    except Exception:
        return -1


# ---------------------------------------------------------------------------
# STEP 3c - live microphone level (proof that Matty is really listening)
# ---------------------------------------------------------------------------
# speech_recognition reads the microphone through source.stream.read(size).
# LevelTap wraps that stream and reports the loudness of every chunk, so the
# UI can draw a real level meter instead of a decorative animation.


class LevelTap:
    """Stream proxy that reports the RMS of every chunk it passes through."""

    def __init__(self, stream, on_level, sample_width=2):
        self._stream = stream
        self._on_level = on_level
        self._width = sample_width

    def read(self, size):
        data = self._stream.read(size)
        if self._on_level is not None:
            try:
                import audioop

                self._on_level(audioop.rms(data, self._width))
            except Exception:
                pass
        return data

    def close(self):
        return self._stream.close()


class tap_levels:
    """Context manager: report mic levels while a phrase is being recorded.

        with tap_levels(source, on_level):
            audio = recognizer.listen(source, ...)
    """

    def __init__(self, source, on_level):
        self.source = source
        self.on_level = on_level
        self._original = None

    def __enter__(self):
        if self.on_level is not None and getattr(self.source, "stream", None) is not None:
            self._original = self.source.stream
            self.source.stream = LevelTap(self._original, self.on_level)
        return self.source

    def __exit__(self, *exc_info):
        if self._original is not None:
            self.source.stream = self._original
            self._original = None
        return False


def flush_stream(source, seconds=0.35):
    """Throw away buffered audio (the tail of Matty's own voice).

    Called right after speaking, so the first thing the next listen() sees is
    the user, not the end of the previous sentence.
    """
    stream = getattr(source, "stream", None)
    if stream is None:
        return
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            stream.read(1024)
        except Exception:
            return


def user_is_talking(source, threshold, chunks=6):
    """Barge-in detector: True when the mic hears a loud, sustained voice.

    Reads a few chunks and compares the loudest one with `threshold`. The
    threshold is deliberately high (see voice loops) so Matty's own speaker
    output does not trigger it on laptop speakers.
    """
    stream = getattr(source, "stream", None)
    if stream is None:
        return False
    loudest = 0
    for _ in range(chunks):
        try:
            data = stream.read(1024)
        except Exception:
            return False
        try:
            import audioop

            loudest = max(loudest, audioop.rms(data, 2))
        except Exception:
            return False
    return loudest >= threshold


# ---------------------------------------------------------------------------
# STEP 4 - Text -> (command, was_woken)
# ---------------------------------------------------------------------------


def extract_wake(text):
    """Split 'hello matty open chrome' into ('open chrome', True).

    Returns (command, woken). When no wake phrase is present the original text
    is returned untouched with woken=False, so the caller can decide whether
    the 2-minute session is still open.
    """
    q = text.lower().strip()
    for phrase in WAKE_PHRASES:
        if phrase in q:
            return q.replace(phrase, " ", 1).strip(" ,.!?"), True
    for word in WAKE_WORDS:
        if word in q:
            return q.replace(word, " ", 1).strip(" ,.!?"), True
    return text.strip(" ,.!?"), False


# ---------------------------------------------------------------------------
# STEP 5 - Command -> reply
# ---------------------------------------------------------------------------
# This step lives in matty_brain.think(). It runs local actions first, then the
# Groq cloud model, then the offline fallback. Both UIs call it, so there is
# exactly one place that decides what Matty answers.


# ---------------------------------------------------------------------------
# STEP 6 - Reply -> spoken audio
# ---------------------------------------------------------------------------


def speak(text):
    """Speak text aloud. Windows uses SAPI (most reliable in threads);
    other platforms use `say` on macOS and pyttsx3 elsewhere."""
    if not text:
        return
    safe_print(f"\n[MATTY]: {text}\n")

    if sys.platform == "darwin":
        subprocess.run(["say", "-v", "Samantha", text])
        return

    if sys.platform.startswith("win"):
        try:
            import pythoncom

            pythoncom.CoInitialize()
            import win32com.client

            win32com.client.Dispatch("SAPI.SpVoice").Speak(text)
            return
        except Exception:
            pass

    try:
        import pyttsx3

        engine = pyttsx3.init()
        engine.say(text)
        engine.runAndWait()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# API key setup (never blocks a background thread)
# ---------------------------------------------------------------------------


def has_api_key():
    """True when a Groq key is available from the environment or key file."""
    return bool(matty_brain._get_api_key())


def ensure_api_key(interactive=None, notify=None):
    """Make sure a Groq key exists. Returns True when the cloud brain is ready.

    IMPORTANT FIX: this used to call getpass() unconditionally. The voice loop
    runs in a background thread, so when no key was stored the prompt blocked
    that thread forever and Matty never started listening. Now we only prompt
    when stdin is a real terminal (interactive=True) and otherwise just report
    the status, so voice always starts even in offline mode.
    """
    if has_api_key():
        return True

    message = (
        "No Groq API key found - running offline. "
        "Click SET KEY in the HUD, or put GROQ_API_KEY=gsk_... in the .env file "
        "(free key: https://console.groq.com/keys)."
    )

    # Decide whether a prompt is even possible.
    if interactive is None:
        interactive = bool(getattr(sys.stdin, "isatty", lambda: False)())

    if not interactive:
        if notify:
            notify(message)
        print(message, flush=True)
        return False

    print(message, flush=True)
    try:
        import getpass

        key = getpass.getpass("Paste Groq API key (or press Enter for offline mode): ")
        key = matty_brain._clean_key(key)
        if not key:
            print("Running in local offline mode.\n", flush=True)
            return False
        # Store it in .env as GROQ_API_KEY (never in a JSON file).
        path = matty_config.save_env_value("GROQ_API_KEY", key)
        print(f"API key saved to {path}.\n", flush=True)
        return True
    except (KeyboardInterrupt, EOFError):
        print("\nSkipping API key. Running in local offline mode.\n", flush=True)
        return False


# ---------------------------------------------------------------------------
# Console-only voice loop (python matty_voice.py)
# ---------------------------------------------------------------------------


def listen_loop():
    """Terminal version of the voice loop: same 6 steps, no window."""
    # STEP 1/2 - key + microphone
    ensure_api_key()
    recognizer = _tuned_recognizer()

    try:
        mic, name, rate = open_microphone()
    except Exception as exc:
        print(f"[NO MIC] {exc}")
        print("Falling back to text console input mode.", flush=True)
        _text_console()
        return

    print(f"[MIC] using {name} at {rate} Hz", flush=True)
    print("\n" + "=" * 58)
    print("  MATTY IS STANDBY. SAY 'HELLO MATTY' TO ACTIVATE")
    print("  The active window lasts 2 minutes.")
    print("=" * 58 + "\n", flush=True)

    active_until = 0.0
    silence_streak = 0

    # Keep the stream open for the whole session (see voice_loop in matty_hud.py
    # for the detailed explanation of why re-opening clips audio).
    source = mic.__enter__()
    try:
        recognizer.adjust_for_ambient_noise(source, duration=1.0)
        while True:
            try:
                # STEP 3b - never record while Matty is talking.
                if SPEECH_ACTIVE.is_set():
                    time.sleep(0.05)
                    continue

                # STEP 3c - live level meter, so you can SEE that it listens.
                with tap_levels(source, _console_level):
                    audio = recognizer.listen(source, timeout=8, phrase_time_limit=7)
                print("\r" + " " * 40 + "\r", end="", flush=True)

                # STEP 3 - audio -> text
                level = audio_level(audio)
                silence_streak = silence_streak + 1 if level == 0 else 0
                if silence_streak == 3:
                    print(
                        "[MIC] receiving pure silence - check Windows microphone "
                        "privacy settings.",
                        flush=True,
                    )

                query = recognize(recognizer, audio)
                print(f'\nYou said: "{query}"', flush=True)

                # STEP 4 - wake word + session handling
                command, woken = extract_wake(query)
                now = time.time()
                if woken:
                    active_until = now + SESSION_SECONDS
                    if not command:
                        speak("Yes, I'm here. What would you like me to do?")
                        continue
                elif now > active_until:
                    print("Ignoring. Say 'hello Matty' to activate.", flush=True)
                    continue
                else:
                    active_until = now + SESSION_SECONDS

                if not command:
                    continue

                # STEP 5 - command -> reply (matty_brain)
                reply = matty_brain.think(command)
                # STEP 6 - reply -> spoken audio
                speak(reply)
                # Drop the tail of our own voice before listening again.
                flush_stream(source)

            except sr.WaitTimeoutError:
                continue
            except sr.UnknownValueError:
                continue
            except SpeechUnavailable as exc:
                print(f"[SPEECH] {exc}", flush=True)
            except KeyboardInterrupt:
                print("\nShutting down Matty. Goodbye!")
                break
            except Exception as exc:
                print(f"\n[Notice]: {exc}", flush=True)
                time.sleep(0.5)
    finally:
        mic.__exit__(None, None, None)


def _console_level(rms):
    """Draw a one-line microphone meter in the terminal."""
    bars = min(20, int(rms / 120))
    print("\rMIC [" + "#" * bars + "-" * (20 - bars) + f"] {rms:5d}", end="", flush=True)


def _tuned_recognizer():
    """Recognizer tuned for short voice commands in a normal room."""
    recognizer = sr.Recognizer()
    recognizer.dynamic_energy_threshold = True
    recognizer.energy_threshold = 300      # starting point, adapts at runtime
    recognizer.pause_threshold = 0.7       # end-of-speech silence (seconds)
    recognizer.non_speaking_duration = 0.4  # audio kept before/after speech
    recognizer.phrase_threshold = 0.25     # ignore very short blips
    return recognizer


def _text_console():
    """Typed fallback when there is no working microphone at all."""
    active_until = 0.0
    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            break
        if not user_input:
            continue
        command, woken = extract_wake(user_input)
        now = time.time()
        if woken:
            active_until = now + SESSION_SECONDS
        elif now > active_until:
            print("Matty: Say 'hello Matty' to activate.")
            continue
        if command:
            speak(matty_brain.think(command))


# ---------------------------------------------------------------------------
# Self-test: python matty_voice.py --test
# ---------------------------------------------------------------------------


def selftest():
    """Check every link of the voice chain and print the result of each step.

    Run this when Matty does not react to your voice: the first step that
    fails tells you exactly what to fix.
    """
    print("\n=== MATTY VOICE SELF-TEST ===")

    # STEP 1 - cloud key
    print(f"[1] Groq API key ....... {'found' if has_api_key() else 'MISSING (offline mode)'}")

    # STEP 2 - devices
    devices = list_input_devices()
    print(f"[2] input devices ...... {len(devices)}")
    for dev in devices:
        flag = "  (loopback, skipped)" if dev["loopback"] else ""
        print(f"      {dev['index']:>2}  {dev['name']}  @ {dev['rate']} Hz{flag}")

    # STEP 3 - open the mic
    try:
        mic, name, rate = open_microphone()
    except Exception as exc:
        print(f"[3] microphone ......... FAILED: {exc}")
        return
    print(f"[3] microphone ......... OK: {name} @ {rate} Hz")

    recognizer = _tuned_recognizer()
    try:
        with mic as source:
            recognizer.adjust_for_ambient_noise(source, duration=1.0)
            print(f"[4] noise threshold .... {int(recognizer.energy_threshold)}")
            print("[5] SPEAK NOW: 'hello matty open chrome' (5 seconds)")
            audio = recognizer.listen(source, timeout=5, phrase_time_limit=5)
    except sr.WaitTimeoutError:
        print("[5] recording .......... nothing heard within 5s (mic works, but silent)")
        return
    except Exception as exc:
        print(f"[5] recording .......... FAILED: {exc}")
        return

    # STEP 3b - loudness tells a quiet room from a blocked microphone
    level = audio_level(audio)
    print(f"[6] audio level ........ {level}" + ("  <- PURE SILENCE: allow mic access" if level == 0 else ""))

    # STEP 4 - speech to text
    try:
        print(f"[7] transcript ......... \"{recognize(recognizer, audio)}\"")
    except sr.UnknownValueError:
        print("[7] transcript ......... nothing intelligible")
    except SpeechUnavailable as exc:
        print(f"[7] transcript ......... FAILED: {exc}")

    print("=== END SELF-TEST ===\n")


if __name__ == "__main__":
    if "--test" in sys.argv:
        selftest()
    else:
        listen_loop()
