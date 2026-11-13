# Deploying Matty to Render

Matty is a **desktop** assistant. Render runs Linux containers with no
microphone, no speakers and no desktop session, so the deployment is split:

| Works on Render | Needs the desktop app |
|---|---|
| AI answers (Groq) | Microphone / speech recognition |
| Live market briefing | Speaking replies (SAPI) |
| YouTube / WhatsApp / mail links | Lock, shutdown, volume, screenshots |
| Hardware meters of the host | Launching local apps, WhatsApp automation |
| The HUD itself | Saved contacts, Gmail SMTP/IMAP |

The web edition exposes only the left column. Every desktop-only button returns
a clear message instead of failing silently, and `set_key` is blocked so a
visitor cannot overwrite your API key.

---

## Files involved

| File | Purpose |
|---|---|
| `server.py` | Flask app: serves the HUD, `/api/action`, `/api/status`, `/api/market`, `/api/vitals`, `/healthz` |
| `requirements-web.txt` | Slim dependency set for the server (no PyAudio, no GUI) |
| `render.yaml` | Render Blueprint (build, start, health check, env vars) |
| `matty_hud.html` | One file, two transports: pywebview on the desktop, `fetch` in the browser |

---

## Deploy in 5 steps

1. **Push the repo** (already done) — Render deploys from `main`.

2. **Open Render** → <https://dashboard.render.com> → **New +** → **Blueprint**.

3. **Connect the repo** `techimran31/Matty`. Render finds `render.yaml`
   automatically and shows a service named `matty`.

4. **Set `GROQ_API_KEY`** when prompted (Environment tab).
   Get a free key at <https://console.groq.com/keys>. It is stored by Render,
   never in the repo — `sync: false` in `render.yaml` enforces that.

5. **Apply**. First build takes ~2 minutes, then you get a URL like
   `https://matty-xxxx.onrender.com`.

---

## Verify the deployment

```bash
curl https://<your-service>.onrender.com/healthz
# {"ok":true}

curl -X POST https://<your-service>.onrender.com/api/action \
  -H "Content-Type: application/json" \
  -d '{"kind":"command","args":{"text":"say hello in Hindi"}}'
# {"result":"नमस्ते!"}
```

Open the URL in a browser: the footer badge shows **ONLINE** when the key works,
and the transcript reports `Web edition: ...` on load.

---

## Configuration

| Variable | Required | Meaning |
|---|---|---|
| `GROQ_API_KEY` | yes | Cloud answers + Whisper transcription |
| `MATTY_LANG` | no | Force a language (`hi-IN`); default is auto-detect |
| `PYTHON_VERSION` | set in yaml | `3.12.7` — 3.13+ removed `audioop` |

---

## Troubleshooting

### `bash: start_matty.bat: command not found`
The service was created manually and Render guessed the start command from the
only "start" file in the repo. Set the Build/Start commands from the table
above, or delete the service and redeploy from the Blueprint.

### `bash: gunicorn: command not found`
The **build** installed `requirements.txt` (desktop) instead of
`requirements-web.txt`, so gunicorn was never installed. Either fix the build
command, or rely on the `gunicorn>=21.2; sys_platform != "win32"` line now
present in `requirements.txt`.

### `Application object must be callable`
The start command is missing `:app` - it must be `gunicorn app:app`, not
`gunicorn app`.

### Page loads but stays OFFLINE
`GROQ_API_KEY` is missing or invalid. Run
`curl -X POST <url>/api/action -H "Content-Type: application/json" -d '{"kind":"test_cloud"}'`
to see the exact provider error.

---

## Free tier notes

- The service **sleeps after 15 minutes** of inactivity; the next request takes
  ~30 s to wake.
- 512 MB RAM is enough — Matty has no model of its own, it calls Groq.
- `--workers 1` keeps the in-memory rate limiter accurate (20 requests / 5 min
  per IP). Scale workers and you should move that to Redis.

---

## Run the web edition locally

```bash
python -m venv .venv-web
.venv-web\Scripts\activate          # Windows
pip install -r requirements-web.txt
python server.py                     # http://127.0.0.1:8000
```

## Deploy the desktop app instead

Render cannot do it. Distribute the repo as-is: `install.bat` (Windows) or
`install.sh` (macOS/Linux), then `start_matty.bat`. The desktop build keeps
`server.py` unused — it is an extra entry point, not a replacement.
