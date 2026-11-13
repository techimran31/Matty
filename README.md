# ⚡ Matty AI Personal Assistant - Complete Setup

> **A real voice-controlled AI executive assistant for your computer.**
> Features voice app launching, YouTube playback, WhatsApp automation, email briefings, live stock market analysis (Buy/Sell calls), rate-limit failover, and a 3D holographic Iron Man HUD!

---

## 🚀 Quick Start (In 60 Seconds)

### On macOS / Linux:
```bash
chmod +x install.sh
./install.sh
```

### On Windows:
Double-click `install.bat` or run:
```cmd
install.bat
```

After setup, launch the Matty on-screen assistant with `start_matty.bat` (or `.venv\Scripts\python.exe matty_ui.py`).
On first launch, paste your free Groq API key when prompted (or press Enter for offline mode).

### Install Matty into Windows
Run `install_matty.bat` once. It creates a **Desktop shortcut** and a **Startup shortcut**, so Matty opens automatically when you log in.

---

## 🎙️ Wake Word & Voice Commands

Matty stays on standby. Say **"Hello Matty"** to activate it, then give tasks normally for the next 2 minutes. Say "Hello Matty" again to reopen the session.

| What You Say | What Matty Does |
| :--- | :--- |
| `"Hello Matty"` | Activates the assistant and waits for a task |
| `"Lock my laptop"` | Locks the screen immediately |
| `"Sleep" / "Shut down" / "Restart"` | Sleeps, shuts down, or restarts the computer |
| `"Sign out"` | Signs out of the current session |
| `"Take a screenshot"` | Opens the screenshot/snipping tool |
| `"Show desktop"` | Minimizes all windows (Windows) |
| `"Open VS Code" / "Open Chrome"` | Launches the application instantly |
| `"Send a message to John saying I will call later"` | Opens WhatsApp with the message drafted |
| `"Send an email to john@example.com about the meeting"` | Opens the mail app with subject and body filled in |
| `"Check my unread emails"` | Reads your unread mail and provides a 30s briefing |
| `"Play lofi on YouTube"` | Opens YouTube and starts playing lofi music |
| `"Stock market report"` | Analyzes Nifty, Sensex, Reliance, Nvidia & crypto |
| `"Should I buy Reliance?"` | Checks moving averages and gives Buy/Sell advice |
| `"Volume up" / "Mute"` | Adjusts your system volume hands-free |

Works on macOS, Windows and Linux. On Windows, apps open via their normal executables and volume control uses the default audio device.

> **Unlock note:** for security, Matty cannot unlock a locked screen. Windows/macOS require your PIN, password or biometric sign-in. Sign in manually, then say "Hello Matty" again.

---

## 🛡️ Best Part: Hybrid Failover (Zero Crashes)
When cloud LLMs hit daily token limits or rate limits (HTTP 429), standard assistants crash and give error messages. 
Matty has an **Automatic Cooldown & Local Fallback Engine**:
- Detects the exact rate-limit duration.
- Switches instantly to offline local code.
- Executes your commands locally without interruption!

---

## 🖥️ On-Screen Assistant Interface
`start_matty.bat` opens an animated dark neon dashboard with:
- pulsing reactor-core orb and live audio waveform
- live **STANDBY / ACTIVE / PROCESSING / SPEAKING** status
- conversation transcript
- **Quick Actions** for YouTube, WhatsApp, Email, Lock and Screenshot
- **Setup Email** and **Add Contact** buttons
- Start / Stop listening controls
- one-click HUD launcher

The window stays on top so you can see when Matty is listening or processing. Voice output uses Windows SAPI for reliable speech, with pyttsx3 as a fallback.

### Send real emails
Click **Setup Email** in the Matty window and enter:
1. Your Gmail address
2. A Gmail **App Password** (create one at https://myaccount.google.com/apppasswords)

The password is stored in Windows Credential Manager, not in a plain file. After that:
- `"Read my unread emails"` actually reads your inbox
- `"Send an email to john@example.com about the meeting"` actually sends it

### Send WhatsApp to a contact name
Click **Add Contact** and save a name → phone number (with country code). Then say:
> "Send a message to John saying I will call later"

Matty sends it through WhatsApp Web. For numbers, say the number directly.

## 🌐 Holographic Iron Man HUD
Double click `matty_workplace.html` in your browser to experience the glowing cyber reactor core, animated globe, live voice audio visualizer, and live market quotes.
