# 🚀 MATTY AI PERSONAL ASSISTANT - Complete Setup Package

**Version:** 2.0 (Executive Edition)  
**Last Updated:** 2026-10-22  
**License:** Open Source & Free to Use  

---

## 📦 What's Inside This Package?

Everything you need to run a **voice-controlled AI personal assistant** with:
- ✅ Voice automation (open apps, play music, web search)
- ✅ WhatsApp auto-replies
- ✅ Unread email briefing (30 seconds)
- ✅ Live stock market analysis + Buy/Sell signals
- ✅ Hybrid cloud + local offline failover (zero crashes)
- ✅ 3D holographic Iron Man HUD dashboard
- ✅ Works on macOS, Windows, and Linux

---

## 🎯 Quick Start (60 Seconds)

### Step 1: System Requirements
- **Python:** 3.10 or newer ([python.org](https://python.org))
- **Free Groq API Key:** Get it free from [console.groq.com/keys](https://console.groq.com/keys)
- **OS:** macOS, Windows 10/11, or Linux

### Step 2: Run Installer
**On macOS / Linux:**
```bash
chmod +x install.sh
./install.sh
```

**On Windows:**
Double-click `install.bat` or open Command Prompt and run:
```cmd
install.bat
```

### Step 3: Get Groq API Key
1. Go to [console.groq.com/keys](https://console.groq.com/keys)
2. Sign up free (takes 2 minutes)
3. Generate an API key
4. Paste it when the installer asks

### Step 4: Launch Matty
**On macOS / Linux:**
```bash
source .venv/bin/activate && python matty_voice.py
```

**On Windows:**
```cmd
start_matty.bat
```

`start_matty.bat` opens the animated dark on-screen assistant dashboard with a pulsing reactor orb, live waveform, and quick actions for YouTube, WhatsApp, Email, Lock and Screenshot. Use `start_matty_console.bat` if you prefer the console-only version.

To install Matty into Windows (Desktop + Startup shortcut), run:
```cmd
install_matty.bat
```

On first launch, paste your free Groq API key when prompted (or press Enter to run offline).

### Step 5: Open Holographic HUD
Open `matty_workplace.html` in your browser (Chrome/Safari) for the 3D Iron Man dashboard.

---

## 🎤 Wake Word & Voice Commands

Say **"Hello Matty"** to activate. The session stays open for 2 minutes, so you can give several tasks without repeating the wake word.

| Command | What Happens |
| :--- | :--- |
| `"Hello Matty"` | Activates the assistant |
| `"Lock my laptop"` | Locks the screen immediately |
| `"Sleep"` / `"Shut down"` / `"Restart"` | Controls laptop power |
| `"Sign out"` | Signs out of the session |
| `"Take a screenshot"` | Opens the screenshot tool |
| `"Show desktop"` | Minimizes all windows (Windows) |
| `"Open VS Code"` / `"Open Chrome"` | Instantly launches the app |
| `"Send a message to John saying I will call later"` | Sends the WhatsApp message (add the contact first) |
| `"Send an email to john@example.com about the meeting"` | Sends the email through Gmail SMTP (set up email first) |
| `"Read all unopened emails"` | Reads unread emails through IMAP (set up email first) |
| `"Play Believer"` / `"Play lofi on YouTube"` | Plays the first matching YouTube video |
| `"Check my unread emails"` | Reads inbox and gives 30-second briefing |
| `"Play lofi on YouTube"` | Opens YouTube and starts playing automatically |
| `"Stock market report"` | Analyzes Nifty, Sensex, Reliance, Nvidia, Bitcoin |
| `"Should I buy Reliance?"` | Checks moving averages and gives Buy/Sell advice |
| `"Volume up"` / `"Mute"` | Hands-free system volume control |
| `"What time is it?"` | Tells current time and date |

> **Unlock:** for security, Matty cannot unlock a locked screen. Sign in manually, then say "Hello Matty" again.

---

## 📁 File Guide

### Core Engine Files
- **`matty_brain.py`** — AI reasoning engine (Groq cloud + local fallback)
- **`matty_voice.py`** — Microphone listener & speech recognition loop
- **`matty_actions.py`** — Local app automation, WhatsApp, email, stock market
- **`matty_market.py`** — Live Yahoo Finance integration with Buy/Sell signals

### Configuration & Setup
- **`requirements.txt`** — Python dependencies (auto-installed)
- **`install.sh`** — macOS/Linux 1-click setup
- **`install.bat`** — Windows 1-click setup

### Documentation & UI
- **`matty_workplace.html`** — Futuristic holographic HUD dashboard
- **`Matty_Setup_Guide.pdf`** — Step-by-step visual guide
- **`README.md`** — Quick cheat sheet
- **`INDEX.md`** — This file

---

## 🛡️ The Failover Gamechanger (Why Matty Never Crashes)

Standard AI assistants break when cloud APIs hit rate limits. Matty doesn't.

**How It Works:**
1. **Cloud Request Sent** → Groq API processes your query at lightning speed
2. **Rate Limit Hit (HTTP 429)?** → Matty detects the exact cooldown duration
3. **Automatic Failover** → Switches to local Python code instantly
4. **Zero Downtime** → Commands execute locally without interruption
5. **User Never Knows** → Seamless handoff, no "API Error" messages

This means: **100% uptime, zero crashes, complete privacy.**

---

## 🌐 Holographic Dashboard Features

Double-click `matty_workplace.html` to open:

- **Central Reactor Core** — Pulsing Iron Man arc reactor heart with orbiting quantum nodes
- **Audio Oscilloscope** — 4-layer neon waveform responding to your voice
- **Live Market Tickers** — Real-time stock quotes with Buy/Sell color coding
- **Neural Pipeline** — Visual flow: MIC → EAR → MIND → HANDS → VOICE
- **System Vitals** — CPU, RAM, Disk, Battery, Uptime live meters
- **Chat Logs & Briefings** — Your voice commands and Matty responses
- **Cyber Grid Effect** — Animated scanlines and particle effects

---

## 🔑 Getting Your Free Groq API Key

1. Visit [console.groq.com](https://console.groq.com)
2. Click **Sign Up** (free forever)
3. Verify your email
4. Go to **API Keys** section
5. Click **Create New Key**
6. Copy the key
7. Paste it when the installer asks

**Free Tier Includes:**
- 200,000 tokens per day (plenty for voice assistant use)
- Ultra-fast inference (2-5ms latency)
- 99.9% uptime SLA

---

## 🖥️ System Requirements Detailed

### Minimum Specs
- **CPU:** Dual-core or better
- **RAM:** 2GB free
- **Disk:** 500MB free for installation + cache
- **Microphone:** Built-in or USB mic
- **Internet:** For cloud Groq API calls (local fallback works offline)

### Recommended Specs
- **CPU:** Quad-core or better
- **RAM:** 4GB+
- **Disk:** 1GB+ SSD (faster startup)

### Supported OS
- **macOS:** 10.14+
- **Windows:** 10/11 (64-bit)
- **Linux:** Ubuntu 18.04+, Debian 10+, Fedora 30+

---

## 🚨 Troubleshooting

### Issue: "I don't hear Matty respond"
**Solution:** Check system volume isn't muted. On macOS, test speech with: `say "hello"`

### Issue: "Microphone not working"
**Solution:** Grant microphone permissions in System Settings → Privacy → Microphone

### Issue: "API key rejected"
**Solution:** Verify the key is correct from [console.groq.com/keys](https://console.groq.com/keys) and paste without extra spaces

### Issue: "Rate limit reached"
**Solution:** This is normal! Matty automatically falls back to local mode. Wait and it'll resume cloud calls after the cooldown.

---

## 📞 Support & Community

- **GitHub Issues:** Report bugs or request features
- **Discord:** Join the community for tips and tricks
- **Twitter:** Follow for updates and demos

---

## 📜 License & Attribution

**Matty AI Personal Assistant v2.0**  
Created with ❤️ for makers, developers, and tech enthusiasts.  
Open source. Free to use, modify, and share.

**Built with:**
- Groq Cloud API (ultra-fast LLM inference)
- SpeechRecognition library (Google Speech API fallback)
- Yahoo Finance API (stock market data)
- Python 3.10+

---

## 🎬 Next Steps After Installation

1. **Speak your first command:** "Matty, open VS Code"
2. **Try market analysis:** "Stock market report"
3. **Open the HUD:** Double-click `matty_workplace.html`
4. **Customize watchlist:** Edit stock tickers in `matty_market.py`
5. **Share with friends:** Send them this INDEX.md or the zip file

---

**Enjoy your personal AI assistant! 🚀⚡**
