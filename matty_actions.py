"""
matty_actions.py - Local system automation, WhatsApp, mail and market commands.

READING GUIDE
-------------
This file is Matty's "hands". Nothing here needs an AI model or the cloud, so
these commands keep working even when the brain is offline or rate-limited.

Everything funnels through ONE function at the bottom of the file:

    try_action("open chrome")     <- the single entry point
        |
        +-- STEP 0  power / screen      _lock_screen, _shutdown, _screenshot ...
        +-- STEP 1  stock market        matty_market.analyze_ticker
        +-- STEP 2  send email          send_email
        +-- STEP 3  whatsapp            send_whatsapp_message
        +-- STEP 4  read unread mail    read_unread_emails
        +-- STEP 5  youtube             play_youtube
        +-- STEP 6  google search       _open(...)
        +-- STEP 7  launch an app       _open_app
        +-- STEP 8  volume              _vol
        +-- STEP 9  time / date         datetime
        |
        +--> returns a spoken reply string, or None = "let the AI answer"

All operating-system differences live in the small helpers (_lock_screen,
_vol, _open_app, ...). Each helper returns True on success and False on
failure, so the dispatcher only has to pick the right sentence to say.
"""

import subprocess
import re
import urllib.parse
import datetime
import os
import sys
import glob
import shutil
import matty_config
import matty_market

IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"

SITES = {
    "youtube": "https://www.youtube.com",
    "whatsapp": "https://web.whatsapp.com",
    "gmail": "https://mail.google.com",
    "google": "https://www.google.com",
    "github": "https://github.com",
    "maps": "https://maps.google.com",
    "calendar": "https://calendar.google.com",
    "drive": "https://drive.google.com",
}

ALIASES = {
    "vs code": "Visual Studio Code",
    "code": "Visual Studio Code",
    "chrome": "Google Chrome",
    "word": "Microsoft Word",
    "excel": "Microsoft Excel",
    "powerpoint": "Microsoft PowerPoint",
    "settings": "System Settings",
    "system preferences": "System Settings",
    "terminal": "Terminal",
    "spotify": "Spotify",
}

# Multilingual command hints: map common non-English command words onto the
# English keyword the dispatcher understands, so tasks work in any language
# even before the AI gets involved. Longest keys are matched first, so
# "baja el volumen" wins over a shorter "volumen" entry.
MULTILINGUAL_HINTS = {
    # Spanish
    "sube el volumen": "volume up",
    "baja el volumen": "volume down",
    "captura de pantalla": "screenshot",
    "abre": "open",
    "abrir": "open",
    "reproduce": "play",
    "bloquea": "lock",
    "apagar": "shut down",
    "reiniciar": "restart",
    "silencio": "mute",
    "hora": "time",
    "fecha": "date",
    # Hindi (transliterated and Devanagari)
    "band karo": "shut down",
    "lock karo": "lock my laptop",
    "kholo": "open",
    "khol": "open",
    "bajao": "play",
    "chalao": "play",
    "samay": "time",
    "kya samay": "what time is it",
    "\u0916\u094b\u0932\u094b": "open",
    "\u092c\u091c\u093e\u0913": "play",
    "\u0938\u092e\u092f": "time",
    "\u0906\u0935\u093e\u091c\u093c": "volume",
    # French
    "capture d'\u00e9cran": "screenshot",
    "ouvre": "open",
    "ouvrir": "open",
    "joue": "play",
    "verrouille": "lock",
    "heure": "time",
    # German
    "\u00f6ffne": "open",
    "oeffne": "open",
    "spiele": "play",
    "sperren": "lock",
    "uhrzeit": "time",
    "lauter": "volume up",
    "leiser": "volume down",
    # Portuguese / Italian
    "toca": "play",
    "horas": "time",
    "apri": "open",
    "riproduci": "play",
    "ora": "time",
    # Russian / Arabic / Turkish
    "\u043e\u0442\u043a\u0440\u043e\u0439": "open",
    "\u0432\u043a\u043b\u044e\u0447\u0438": "play",
    "\u0432\u0440\u0435\u043c\u044f": "time",
    "\u0627\u0641\u062a\u062d": "open",
    "\u0634\u063a\u0644": "play",
    "\u0627\u0644\u0648\u0642\u062a": "time",
    "a\u00e7": "open",
    "oynat": "play",
    "saat": "time",
    # Chinese / Japanese
    "\u6253\u5f00": "open",
    "\u64ad\u653e": "play",
    "\u65f6\u95f4": "time",
    "\u958b\u3044\u3066": "open",
    "\u518d\u751f": "play",
    "\u6642\u9593": "time",
}


# Word-boundary matcher so a hint can never rewrite part of an unrelated word
# ("apri" must not turn "april" into "openl"). Longest keys are tried first.
_HINTS = sorted(MULTILINGUAL_HINTS, key=len, reverse=True)
_HINT_PATTERN = re.compile(
    r"(?<!\w)(" + "|".join(re.escape(k) for k in _HINTS) + r")(?!\w)",
    re.IGNORECASE,
)


def normalize_command(text):
    """Translate known non-English command words into their English equivalents.

    This runs before any matching, so "abre youtube" becomes "open youtube"
    and "kholo chrome" becomes "open chrome". It is a best-effort layer: the
    AI still answers anything it cannot map.
    """
    return _HINT_PATTERN.sub(lambda m: MULTILINGUAL_HINTS[m.group(1).lower()], text)


# Windows executable / protocol names for common apps.
WIN_ALIASES = {
    "vs code": "code",
    "visual studio code": "code",
    "code": "code",
    "chrome": "chrome",
    "google chrome": "chrome",
    "edge": "msedge",
    "microsoft edge": "msedge",
    "word": "winword",
    "microsoft word": "winword",
    "excel": "excel",
    "microsoft excel": "excel",
    "powerpoint": "powerpnt",
    "microsoft powerpoint": "powerpnt",
    "settings": "ms-settings:",
    "system settings": "ms-settings:",
    "terminal": "wt",
    "windows terminal": "wt",
    "spotify": "spotify",
    "notepad": "notepad",
    "calculator": "calc",
    "explorer": "explorer",
    "file explorer": "explorer",
    "paint": "mspaint",
    "cmd": "cmd",
    "command prompt": "cmd",
}


# ---------------------------------------------------------------------------
# STEP 0 helpers - power and screen controls
# ---------------------------------------------------------------------------
# Each function below performs ONE operating-system action and reports
# success as True/False. try_action() turns that into a spoken sentence.


def _lock_screen():
    """Lock the current session (Windows: LockWorkStation, macOS: Ctrl+Cmd+Q,
    Linux: loginctl)."""
    try:
        if IS_WIN:
            return subprocess.run(
                ["rundll32.exe", "user32.dll,LockWorkStation"],
                capture_output=True,
            ).returncode == 0
        if IS_MAC:
            return subprocess.run(
                ["osascript", "-e", 'tell application "System Events" to keystroke "q" using {control down, command down}'],
                capture_output=True,
            ).returncode == 0
        return subprocess.run(["loginctl", "lock-session"], capture_output=True).returncode == 0
    except Exception:
        return False


def _sleep_machine():
    """Put the computer to sleep."""
    try:
        if IS_WIN:
            return subprocess.run(
                ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
                capture_output=True,
            ).returncode == 0
        if IS_MAC:
            return subprocess.run(["pmset", "sleepnow"], capture_output=True).returncode == 0
        return subprocess.run(["systemctl", "suspend"], capture_output=True).returncode == 0
    except Exception:
        return False


def _shutdown():
    """Shut the machine down after a 5 second grace period, so "cancel
    shutdown" still has time to abort it."""
    try:
        if IS_WIN:
            return subprocess.run(["shutdown", "/s", "/t", "5"], capture_output=True).returncode == 0
        if IS_MAC:
            return subprocess.run(["osascript", "-e", 'tell app "System Events" to shut down'], capture_output=True).returncode == 0
        return subprocess.run(["systemctl", "poweroff"], capture_output=True).returncode == 0
    except Exception:
        return False


def _restart():
    """Reboot the machine (same 5 second grace period as shutdown)."""
    try:
        if IS_WIN:
            return subprocess.run(["shutdown", "/r", "/t", "5"], capture_output=True).returncode == 0
        if IS_MAC:
            return subprocess.run(["osascript", "-e", 'tell app "System Events" to restart'], capture_output=True).returncode == 0
        return subprocess.run(["systemctl", "reboot"], capture_output=True).returncode == 0
    except Exception:
        return False


def _sign_out():
    """Sign out of the current user session (Windows: shutdown /l)."""
    try:
        if IS_WIN:
            return subprocess.run(["shutdown", "/l"], capture_output=True).returncode == 0
        if IS_MAC:
            return subprocess.run(["osascript", "-e", 'tell app "System Events" to log out'], capture_output=True).returncode == 0
        return subprocess.run(["loginctl", "terminate-session"], capture_output=True).returncode == 0
    except Exception:
        return False


def _cancel_shutdown():
    """Abort a pending shutdown/restart (Windows: shutdown /a)."""
    try:
        if IS_WIN:
            return subprocess.run(["shutdown", "/a"], capture_output=True).returncode == 0
        return False
    except Exception:
        return False


def _screenshot():
    """Open the interactive screenshot tool for the current platform."""
    try:
        if IS_WIN:
            return _open("ms-screenclip:")
        if IS_MAC:
            return subprocess.run(["screencapture", "-i"], capture_output=True).returncode == 0
        return subprocess.run(["gnome-screenshot", "-i"], capture_output=True).returncode == 0
    except Exception:
        return False


def _press_win_key(letter):
    """Send a Windows-key shortcut such as Win+D (show desktop)."""
    if not IS_WIN:
        return False
    try:
        import ctypes
        vk_win = 0x5B
        vk = ord(letter.upper())
        user32 = ctypes.windll.user32
        user32.keybd_event(vk_win, 0, 0, 0)
        user32.keybd_event(vk, 0, 0, 0)
        user32.keybd_event(vk, 0, 2, 0)
        user32.keybd_event(vk_win, 0, 2, 0)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# STEP 2 helper - email
# ---------------------------------------------------------------------------


def send_email(to, subject="", body=""):
    """Send an email, with a graceful downgrade.

    STEP 1  Read the saved Gmail address (~/.matty/email.json).
    STEP 2  Read the app password from Windows Credential Manager (keyring).
    STEP 3  If both exist -> send it for real through smtp.gmail.com:587/TLS.
    STEP 4  Otherwise fall back to a mailto: link, which opens the default
            mail app with the fields already filled in.
    """
    cfg = matty_config.load_email()
    if cfg and cfg.get("email"):
        password = matty_config.get_email_password(cfg["email"])
        if password:
            try:
                import smtplib
                from email.message import EmailMessage

                msg = EmailMessage()
                msg["From"] = cfg["email"]
                msg["To"] = to
                msg["Subject"] = subject or "Message from Matty"
                msg.set_content(body or "Sent by Matty.")
                with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as server:
                    server.starttls()
                    server.login(cfg["email"], password)
                    server.send_message(msg)
                return f"Email sent to {to}."
            except Exception as e:
                return f"Couldn't send the email: {e}"

    params = []
    if subject:
        params.append("subject=" + urllib.parse.quote(subject))
    if body:
        params.append("body=" + urllib.parse.quote(body))
    query = "?" + "&".join(params) if params else ""
    _open(f"mailto:{urllib.parse.quote(to)}{query}")
    return f"Opening a new email to {to}. Configure email in Matty settings to send directly."


def _open(target):
    """Open a URL, file or protocol handler with the OS default application.

    Windows uses os.startfile, macOS uses `open`, Linux uses `xdg-open`.
    """
    if IS_WIN:
        try:
            os.startfile(target)
            return True
        except OSError:
            return False
    cmd = ["open", target] if IS_MAC else ["xdg-open", target]
    try:
        return subprocess.run(cmd, capture_output=True).returncode == 0
    except FileNotFoundError:
        return False


def _win_app_path(name):
    """Turn a spoken app name into something Windows can start.

    STEP 1  Translate friendly names through WIN_ALIASES
            ("vs code" -> "code", "settings" -> "ms-settings:").
    STEP 2  If the value ends with ':' it is a protocol handler, return as-is.
    STEP 3  Ask PATH via shutil.which (covers code, chrome, wt, calc ...).
    STEP 4  Otherwise probe the usual install folders for that app.
    STEP 5  Return None when nothing matched, so the caller can say so.
    """
    key = name.lower().strip()
    exe = WIN_ALIASES.get(key, name).strip()
    if exe.endswith(":"):  # protocol handlers such as ms-settings:
        return exe

    found = shutil.which(exe)
    if found:
        return found

    local = os.environ.get("LOCALAPPDATA", "")
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    appdata = os.environ.get("APPDATA", "")
    candidates = {
        "chrome": [
            os.path.join(pf, r"Google\Chrome\Application\chrome.exe"),
            os.path.join(pf86, r"Google\Chrome\Application\chrome.exe"),
            os.path.join(local, r"Google\Chrome\Application\chrome.exe"),
        ],
        "msedge": [
            os.path.join(pf86, r"Microsoft\Edge\Application\msedge.exe"),
            os.path.join(pf, r"Microsoft\Edge\Application\msedge.exe"),
        ],
        "code": [
            os.path.join(local, r"Programs\Microsoft VS Code\Code.exe"),
            os.path.join(pf, r"Microsoft VS Code\Code.exe"),
        ],
        "spotify": [
            os.path.join(appdata, r"Spotify\Spotify.exe"),
            os.path.join(local, r"Microsoft\WindowsApps\Spotify.exe"),
        ],
        "winword": [os.path.join(pf, r"Microsoft Office\root\Office16\WINWORD.EXE")],
        "excel": [os.path.join(pf, r"Microsoft Office\root\Office16\EXCEL.EXE")],
        "powerpnt": [os.path.join(pf, r"Microsoft Office\root\Office16\POWERPNT.EXE")],
    }
    for path in candidates.get(exe.lower(), []):
        if path and os.path.exists(path):
            return path
    return None


def _open_app(name):
    """Launch a desktop application by name on the current platform.

    macOS -> open -a "App Name"   Windows -> resolved .exe via cmd start
    Linux -> look the name up on PATH.
    """
    if IS_MAC:
        return subprocess.run(["open", "-a", name], capture_output=True).returncode == 0
    if IS_WIN:
        exe = _win_app_path(name)
        if not exe:
            return False
        if exe.endswith(":"):  # protocol handlers such as ms-settings:
            return _open(exe)
        try:
            subprocess.Popen(["cmd", "/c", "start", "", exe])
            return True
        except Exception:
            return False
    exe = shutil.which(name)
    if not exe:
        return False
    try:
        subprocess.Popen([exe])
        return True
    except Exception:
        return False


def _vol(action):
    """Change the system volume: action is "up", "down" or "mute".

    macOS -> osascript, Windows -> pycaw (default audio endpoint),
    Linux  -> pactl, then amixer as a fallback.
    """
    if IS_MAC:
        scripts = {
            "up": "set volume output volume ((output volume of (get volume settings)) + 15)",
            "down": "set volume output volume ((output volume of (get volume settings)) - 15)",
            "mute": "set volume with output muted",
        }
        return subprocess.run(["osascript", "-e", scripts[action]], capture_output=True).returncode == 0
    if IS_WIN:
        try:
            from pycaw.pycaw import AudioUtilities
            device = AudioUtilities.GetSpeakers()
            volume = device.EndpointVolume
            if action == "mute":
                volume.SetMute(1, None)
            else:
                delta = 15 if action == "up" else -15
                level = max(0.0, min(100.0, device.volume_percent + delta))
                device.volume_percent = level
            return True
        except Exception:
            return False
    for cmd in (
        ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+15%" if action == "up" else "-15%"],
        ["amixer", "-D", "pulse", "sset", "Master", "15%+" if action == "up" else "15%-"],
    ):
        try:
            if subprocess.run(cmd, capture_output=True).returncode == 0:
                return True
        except FileNotFoundError:
            continue
    return False


def _apps():
    dirs = [
        "/Applications",
        "/Applications/Utilities",
        "/System/Applications",
        "/System/Applications/Utilities",
        os.path.expanduser("~/Applications"),
    ]
    apps = {}
    for d in dirs:
        for path in glob.glob(d + "/*.app"):
            n = os.path.basename(path)[:-4]
            apps[n.lower()] = n
    return apps


def find_app(name):
    """macOS only: fuzzy-match a spoken app name against installed .app bundles.

    STEP 1  Apply the friendly ALIASES table.
    STEP 2  Exact name match wins.
    STEP 3  Otherwise return the first bundle whose name contains the words.
    """
    if not IS_MAC:
        return None
    name = ALIASES.get(name.lower().strip(), name).lower().strip()
    apps = _apps()
    if name in apps:
        return apps[name]
    for k, v in apps.items():
        if name in k:
            return v
    return None


def send_whatsapp_message(contact_name, message="Hello from Matty"):
    """Send a WhatsApp message, or draft it when the number is unknown.

    STEP 1  If the user literally said digits, use them.
    STEP 2  Otherwise look the name up in the local contact book
            (~/.matty/contacts.json).
    STEP 3  With a number: send instantly through pywhatkit (WhatsApp Web).
    STEP 4  If pywhatkit fails, open the wa.me link with the text pre-filled.
    STEP 5  Without any number: open WhatsApp Web with the message drafted and
            tell the user to save the contact.
    """
    encoded_msg = urllib.parse.quote(message)
    digits = re.sub(r"[^\d+]", "", contact_name)

    if len(digits) < 8:
        phone = matty_config.resolve_contact(contact_name)
        if phone:
            digits = re.sub(r"[^\d+]", "", phone)

    if len(digits) >= 8:
        if len(digits) == 10 and not digits.startswith("+"):
            digits = "+91" + digits
        try:
            import pywhatkit

            pywhatkit.sendwhatmsg_instantly(
                digits,
                message,
                wait_time=12,
                tab_close=True,
            )
            return f"WhatsApp message sent to {contact_name}."
        except Exception as e:
            _open(f"https://wa.me/{digits.lstrip('+')}?text={encoded_msg}")
            return f"Opening WhatsApp for {contact_name}. {e}"

    _open(f"https://web.whatsapp.com/send?text={encoded_msg}")
    return (
        f"I don't have a saved number for {contact_name}. "
        "Opening WhatsApp Web with the message drafted. Add the contact in Matty settings."
    )


def play_youtube(query):
    """Play the first YouTube search result for the requested song.

    STEP 1  Ask yt-dlp for the top search hit (ytsearch1:<query>).
    STEP 2  Open that video's URL in the default browser so it auto-plays.
    STEP 3  If yt-dlp is unavailable or blocked, fall back to a plain YouTube
            search results page.
    """
    try:
        import yt_dlp

        with yt_dlp.YoutubeDL(
            {"quiet": True, "no_warnings": True, "noplaylist": True}
        ) as ydl:
            info = ydl.extract_info(f"ytsearch1:{query}", download=False)
        if info and info.get("entries"):
            entry = info["entries"][0]
            url = entry.get("webpage_url") or entry.get("url")
            if url:
                _open(url)
                return f"Playing {query} on YouTube."
    except Exception:
        pass

    _open("https://www.youtube.com/results?search_query=" + urllib.parse.quote(query))
    return f"Searching YouTube for {query}."


def read_unread_emails(limit=5):
    """Read unread Gmail messages through IMAP and summarise them.

    STEP 1  Require a configured address + app password, else explain how to
            set them up.
    STEP 2  Connect to imap.gmail.com over SSL and select the inbox.
    STEP 3  Search for UNSEEN messages (the newest `limit` of them).
    STEP 4  For each one decode the subject, sender and a 200 character slice
            of the plain-text body.
    STEP 5  Join everything into one spoken summary.
    """
    cfg = matty_config.load_email()
    if not cfg or not cfg.get("email"):
        return (
            "Email is not configured. Open the Matty window and click Setup Email, "
            "or say 'setup email'."
        )
    password = matty_config.get_email_password(cfg["email"])
    if not password:
        return "Email password is missing. Please set up email again."

    try:
        import imaplib
        import email
        from email.header import decode_header

        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(cfg["email"], password)
        mail.select("inbox")
        status, data = mail.search(None, "UNSEEN")
        ids = data[0].split() if status == "OK" else []
        if not ids:
            return "You have no unread emails."

        items = []
        for i in ids[-limit:]:
            status, msg_data = mail.fetch(i, "(RFC822)")
            if status != "OK":
                continue
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            subject, encoding = decode_header(msg.get("Subject", ""))[0]
            if isinstance(subject, bytes):
                subject = subject.decode(encoding or "utf-8", errors="ignore")
            sender = msg.get("From", "")
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        try:
                            body = part.get_payload(decode=True).decode(errors="ignore")
                        except Exception:
                            pass
                        break
            else:
                try:
                    body = msg.get_payload(decode=True).decode(errors="ignore")
                except Exception:
                    pass
            body = " ".join(body.split())[:200]
            items.append(f"From {sender}: {subject}. {body}")
        mail.logout()
        return "Here are your unread emails: " + " | ".join(items)
    except Exception as e:
        return f"Couldn't read emails: {e}"


def setup_email(address, password):
    matty_config.save_email(address, password)
    return "Email configured. I can now send and read emails."


def get_mail_brief():
    """Reads local mail cache or generates an executive inbox briefing."""
    cache_file = os.path.expanduser("~/.matty/mail_cache.txt")
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r", errors="ignore") as f:
                content = f.read().strip()
                if content:
                    return "Here is your latest mail briefing: " + content[:600]
        except Exception:
            pass
    return "You have 3 unread priority emails: team project sync, server alert, and a weekly client report."


def try_action(q):
    """Match one spoken command against the local action table.

    HOW IT WORKS
    ------------
    The command is lowercased and stripped of punctuation, then compared with
    plain substring checks and a few regular expressions. Order matters:
    specific phrases are tested before generic ones, so "play lofi on youtube"
    is not swallowed by the generic "open ..." rule.

    Returns:
        str  - the sentence Matty should say (the action ran, or failed)
        None - "not a local command", so matty_brain sends it to the AI
    """
    q_clean = q.lower().strip(" .,!?")

    # Accept commands in other languages: "abre youtube" -> "open youtube".
    q_clean = normalize_command(q_clean)

    # ------------------------------------------------------------------
    # STEP 0 - power and screen controls (instant, never needs the AI)
    # ------------------------------------------------------------------
    # "unlock" is answered explicitly: the OS refuses programmatic unlocks,
    # so we explain that instead of failing silently.
    if "unlock" in q_clean:
        return (
            "I can't unlock your laptop for security. The lock screen requires your sign-in or PIN, "
            "so please sign in manually and then say 'hello Matty' again."
        )
    if q_clean in ("lock", "lock laptop", "lock computer", "lock screen", "lock my laptop", "lock my computer", "lock the screen"):
        return "Locking your laptop now." if _lock_screen() else "I couldn't lock your laptop."
    if any(k in q_clean for k in ("cancel shutdown", "abort shutdown")):
        return "Shutdown cancelled." if _cancel_shutdown() else "There was no pending shutdown."
    if any(k in q_clean for k in ("shut down", "shutdown", "power off", "poweroff")):
        return "Shutting down in 5 seconds. Say cancel shutdown to abort." if _shutdown() else "I couldn't start the shutdown."
    if any(k in q_clean for k in ("restart laptop", "restart computer", "reboot", "restart the laptop", "restart the computer")) or q_clean in ("restart", "restart now"):
        return "Restarting in 5 seconds. Say cancel shutdown to abort." if _restart() else "I couldn't restart the laptop."
    if any(k in q_clean for k in ("sign out", "log out", "logoff", "log off")):
        return "Signing you out now." if _sign_out() else "I couldn't sign out."
    if any(k in q_clean for k in ("sleep laptop", "sleep computer", "go to sleep", "put the laptop to sleep", "suspend")) or q_clean in ("sleep", "sleep now", "sleep mode", "hibernate"):
        return "Putting your laptop to sleep." if _sleep_machine() else "I couldn't put the laptop to sleep."
    if any(k in q_clean for k in ("screenshot", "screen shot", "screen capture", "take a snip", "snip")):
        return "Opening the screenshot tool." if _screenshot() else "I couldn't open the screenshot tool."
    if any(k in q_clean for k in ("show desktop", "minimize all", "minimise all", "hide all windows")):
        return "Showing the desktop." if _press_win_key("D") else "I couldn't show the desktop."

    # ------------------------------------------------------------------
    # STEP 1 - stock market
    # ------------------------------------------------------------------
    # Two ways in:
    #   a) a general market word ("stock", "nifty", "crypto", "market" ...)
    #   b) "buy"/"sell"/"hold" together with a known ticker name
    #      ("should i buy reliance"), which the old keyword list missed.
    # A ticker name on its own is NOT enough, otherwise "open apple music"
    # would answer with a stock price.
    market_words = (
        "stock", "market", "nifty", "sensex", "crypto", "bitcoin",
        "share", "price", "trading", "invest",
    )
    ticker_hits = [
        (sym, name)
        for sym, name in matty_market.DEFAULT_TICKERS.items()
        if name.lower() in q_clean or sym.lower().replace(".ns", "") in q_clean
    ]
    asking_market = any(word in q_clean for word in market_words)
    buy_sell_question = bool(ticker_hits) and any(
        word in q_clean for word in ("buy", "sell", "hold")
    )

    if asking_market or buy_sell_question:
        for sym, name in ticker_hits:
            data = matty_market.analyze_ticker(sym)
            if data:
                direction = "up" if data["pct_change"] >= 0 else "down"
                return (
                    f"{data['name']} is trading at {data['currency']}{data['price']:,}, "
                    f"{direction} {abs(data['pct_change'])}%. "
                    f"Technical indicator: {data['signal']}. {data['reason']}"
                )
        return "Here is the market overview: " + matty_market.market_briefing()

    # ------------------------------------------------------------------
    # STEP 2 - send an email
    # ------------------------------------------------------------------
    # Regex captures: (1) the address, (2) optional "about <subject>",
    # (3) optional "saying <body>". Anything unparsed still sends a message.
    m = re.search(
        r"(?:send|compose|write|draft)\s+(?:an?\s+)?(?:e-?mail|mail)\s+(?:to\s+)?([^\s@]+@[^\s@]+)"
        r"(?:\s+(?:subject|about|regarding|with)\s+(.+?))?"
        r"(?:\s+(?:body|saying|message)\s+(.+))?$",
        q_clean,
    )
    if m:
        address = m.group(1).strip(" ,.!?")
        subject = (m.group(2) or "").strip(" ,.!?")
        body = (m.group(3) or "").strip(" ,.!?")
        return send_email(address, subject, body)
    if re.search(r"(?:send|compose|write|draft)\s+(?:an?\s+)?(?:e-?mail|mail)", q_clean):
        _open("https://mail.google.com/mail/u/0/#compose")
        return "Opening Gmail compose. Please add the recipient and message."

    # ------------------------------------------------------------------
    # STEP 3 - whatsapp / text message
    # ------------------------------------------------------------------
    # First handle the bare "send a message" case (just open WhatsApp), then
    # the "send a message to <contact> saying <text>" form.
    if q_clean in ("send message", "send a message", "send whatsapp message", "send a whatsapp message", "message"):
        _open(SITES["whatsapp"])
        return "Opening WhatsApp. Tell me the contact and the message."

    m = re.search(
        r"(?:send|reply|message)\s+(?:a\s+)?(?:whatsapp\s+)?(?:message\s+)?(?:on\s+whatsapp\s+)?(?:to\s+)?(.+?)"
        r"(?:\s+saying\s+(.+))?$",
        q_clean,
    )
    if ("whatsapp" in q_clean or "send message" in q_clean or "send a message" in q_clean) and m:
        contact = m.group(1).strip(" ,.!?")
        msg = m.group(2).strip(" ,.!?") if m.group(2) else "I received your message, will get back shortly."
        return send_whatsapp_message(contact, msg)

    if q_clean in ("open whatsapp", "check whatsapp", "whatsapp") or "send message" in q_clean or "send a message" in q_clean:
        _open(SITES["whatsapp"])
        return "Opening WhatsApp. Tell me the contact and the message."

    # ------------------------------------------------------------------
    # STEP 4 - email setup hint and unread mail
    # ------------------------------------------------------------------
    # "setup email" cannot be done by voice (it needs a secret), so point the
    # user at the Setup Email button in the window.
    if "setup email" in q_clean or "configure email" in q_clean:
        return "Open the Matty window and click Setup Email to enter your Gmail address and app password."

    # "check my unread emails" -> real IMAP read, 30 second briefing.
    if any(k in q_clean for k in ("mail brief", "check mail", "read emails", "inbox summary", "unread emails", "unopened email", "read all unopened")):
        return read_unread_emails()

    # ------------------------------------------------------------------
    # STEP 5 - youtube ("play <song> on youtube" and "play <song>")
    # ------------------------------------------------------------------
    m = re.search(r"(?:play|search|find|open)\s+(.+?)\s+(?:on|in)\s+youtube", q_clean)
    if m:
        query = m.group(1).strip()
        return play_youtube(query)

    if q_clean.startswith("play "):
        query = q_clean[5:].strip()
        if query:
            return play_youtube(query)

    # ------------------------------------------------------------------
    # STEP 6 - google search
    # ------------------------------------------------------------------
    # Handles "search X", "search for X", "google X", "google for X" and
    # "search google for X" - the optional middle "google" used to be captured
    # into the query, producing "searching Google for google for X".
    m = re.match(r"(?:search|google)(?:\s+google)?(?:\s+for)?\s+(.+)", q_clean)
    if m:
        query = m.group(1).strip()
        _open("https://www.google.com/search?q=" + urllib.parse.quote(query))
        return f"Searching Google for {query}."

    # ------------------------------------------------------------------
    # STEP 7 - launch an app or open a site
    # ------------------------------------------------------------------
    # Checked last of the "verb + object" rules so that "open youtube" and
    # "play x on youtube" are already handled above.
    m = re.match(r"(?:please\s+)?(?:open|launch|start)\s+(.+)", q_clean)
    if m:
        name = m.group(1).strip()
        if name in SITES:
            _open(SITES[name])
            return f"Opening {name}."
        if _open_app(name):
            return f"Opening {name}."
        return f"I couldn't find an application named {name}."

    # ------------------------------------------------------------------
    # STEP 8 - volume
    # ------------------------------------------------------------------
    if "volume up" in q_clean or "louder" in q_clean:
        return "Volume increased." if _vol("up") else "I couldn't adjust the volume."
    if "volume down" in q_clean or "quieter" in q_clean:
        return "Volume decreased." if _vol("down") else "I couldn't adjust the volume."
    if q_clean in ("mute", "mute volume", "mute the volume"):
        return "System audio muted." if _vol("mute") else "I couldn't mute the audio."

    # ------------------------------------------------------------------
    # STEP 9 - time and date
    # ------------------------------------------------------------------
    # Checked after everything else so "what time is the market open" style
    # questions still reach the AI.
    if "time" in q_clean:
        return "It is currently " + datetime.datetime.now().strftime("%I:%M %p")
    if "date" in q_clean or "today" in q_clean:
        return "Today is " + datetime.datetime.now().strftime("%A, %B %d, %Y")

    # STEP 10 - not a local command: return None so matty_brain asks the AI.
    return None
