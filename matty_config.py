"""
matty_config.py - Small local settings store for Matty.

READING GUIDE
-------------
Three things are persisted, each in the safest place available:

    STEP 1  email address    -> ~/.matty/email.json          (plain text, fine)
    STEP 2  email password   -> Windows Credential Manager   (keyring, encrypted)
    STEP 3  whatsapp contacts-> ~/.matty/contacts.json       (name -> number)

A password never touches the disk: keyring hands it to the OS secret store.
If keyring is missing, get_email_password() simply returns None and the email
features degrade to opening a mailto: link instead of failing.
"""

import json
import os

try:
    import keyring
except Exception:  # keyring is optional at runtime
    keyring = None

CONFIG_DIR = os.path.expanduser("~/.matty")
EMAIL_FILE = os.path.join(CONFIG_DIR, "email.json")
CONTACTS_FILE = os.path.join(CONFIG_DIR, "contacts.json")
KEYRING_SERVICE = "matty-email"

# ---------------------------------------------------------------------------
# STEP 4 - .env support (API keys live here, never in a JSON file)
# ---------------------------------------------------------------------------
# The .env file is looked up in the app folder first, then in the parent folder,
# so it works whether you keep it next to the code or one level up.
# Real environment variables always win over .env values.
APP_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_NAME = ".env"


def env_path():
    """Return the .env file to use: app folder, else parent folder, else app."""
    local = os.path.join(APP_DIR, ENV_NAME)
    if os.path.exists(local):
        return local
    parent = os.path.join(os.path.dirname(APP_DIR), ENV_NAME)
    if os.path.exists(parent):
        return parent
    return local


def load_env(path=None):
    """Read KEY=VALUE lines from .env into os.environ.

    STEP 1  open the file (missing file is not an error)
    STEP 2  skip blank lines and # comments
    STEP 3  split on the FIRST '=' only, so values may contain '='
    STEP 4  strip surrounding quotes
    STEP 5  setdefault: a real environment variable is never overwritten
    """
    path = path or env_path()
    loaded = {}
    try:
        with open(path, encoding="utf-8") as handle:
            for raw in handle:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                name, value = line.split("=", 1)
                name = name.strip()
                value = value.strip().strip('"').strip("'").strip()
                if not name:
                    continue
                loaded[name] = value
                os.environ.setdefault(name, value)
    except FileNotFoundError:
        pass
    except Exception:
        pass
    return loaded


def save_env_value(name, value, path=None):
    """Create or update one KEY=VALUE line in .env, keeping every other line.

    STEP 1  read the existing lines (empty list when the file is new)
    STEP 2  replace the matching key in place, or append it
    STEP 3  write the file back and lock it down to the current user
    STEP 4  update os.environ so the new value is live immediately
    """
    path = path or env_path()

    # STEP 1 - existing content
    lines = []
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except FileNotFoundError:
        lines = []

    # STEP 2 - replace or append
    replaced = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(f"{name}=") or stripped.startswith(f"{name} ="):
            lines[index] = f"{name}={value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{name}={value}")

    # STEP 3 - write
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass

    # STEP 4 - live value
    os.environ[name] = value
    return path


def _ensure_dir():
    """Create ~/.matty on first use (mkdir -p behaviour)."""
    os.makedirs(CONFIG_DIR, exist_ok=True)


def load_email():
    """Return {"email": "..."} or None when email was never configured."""
    try:
        with open(EMAIL_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_email(email, password=None):
    """Store the address on disk and the app password in the OS keyring.

    STEP 1  Create ~/.matty if needed.
    STEP 2  Merge into the existing JSON so other keys are preserved.
    STEP 3  Hand the password to keyring (never write it to a file).
    """
    _ensure_dir()
    data = load_email() or {}
    data["email"] = email.strip()
    with open(EMAIL_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)
    if password and keyring is not None:
        try:
            keyring.set_password(KEYRING_SERVICE, email.strip(), password)
        except Exception:
            pass


def get_email_password(email):
    """Fetch the app password from the OS keyring (None if unavailable)."""
    if keyring is None:
        return None
    try:
        return keyring.get_password(KEYRING_SERVICE, email)
    except Exception:
        return None


def load_contacts():
    """Return the contact book as {lowercase name: phone number}."""
    try:
        with open(CONTACTS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_contacts(contacts):
    """Write the whole contact book back to ~/.matty/contacts.json."""
    _ensure_dir()
    with open(CONTACTS_FILE, "w", encoding="utf-8") as f:
        json.dump(contacts, f, indent=2)


def add_contact(name, phone):
    """Save one contact (names are lowercased so lookups are case-insensitive)."""
    contacts = load_contacts()
    contacts[name.strip().lower()] = phone.strip()
    save_contacts(contacts)
    return contacts[name.strip().lower()]


def resolve_contact(name):
    """Look up a spoken contact name and return the phone number or None."""
    contacts = load_contacts()
    return contacts.get(name.strip().lower())
