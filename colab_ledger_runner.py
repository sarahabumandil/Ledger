# colab_ledger_runner.py
#
# Paste this into a Google Colab notebook, split at the "# %%" markers
# (Colab / Jupytext will treat each as its own cell). Run top to bottom
# every time you start a fresh runtime.
#
# WHAT THIS DOES
#   1. Clones your Ledger repo and installs requirements.txt
#   2. Reads your secrets from Colab's "Secrets" pane (never hardcoded)
#   3. Starts your FastAPI app with uvicorn, in a background thread
#   4. Opens an ngrok tunnel to it and grabs the public HTTPS URL
#   5. Adds a lightweight shared-secret check so randoms who find the
#      URL in your public repo can't spend your API credits
#   6. Writes that URL into api-config.json in your GitHub repo via the
#      Contents API (creating the file the first time, updating it on
#      every subsequent run)
#
# IMPORTANT CAVEATS (read before relying on this):
#   - Google Colab's terms don't permit using it as a persistent backend
#     host. This WILL disconnect (idle timeout, ~12h max session, random
#     recycles) and every disconnect means a new URL + a new commit.
#   - Your repo is public, so the moment this pushes api-config.json,
#     the live endpoint is visible to anyone. The X-Api-Key check below
#     is a minimum viable guard, not real security.
#   - raw.githubusercontent.com is CDN-cached for a few minutes, so the
#     frontend may briefly load a stale URL after each restart.

# %%
# --- Cell 1: clone + install -------------------------------------------
import os

REPO_OWNER = "sarahabumandil"
REPO_NAME = "Ledger"
REPO_URL = f"https://github.com/{REPO_OWNER}/{REPO_NAME}.git"
LOCAL_DIR = f"/content/{REPO_NAME}"

if os.path.exists(LOCAL_DIR):
    get_ipython().system(f"cd {LOCAL_DIR} && git pull")
else:
    get_ipython().system(f"git clone {REPO_URL} {LOCAL_DIR}")

get_ipython().system(f"pip install -q -r {LOCAL_DIR}/requirements.txt pyngrok requests")

# %%
# --- Cell 2: load secrets from Colab's Secrets pane ---------------------
# Click the key icon in the left sidebar, add each of these, then toggle
# "Notebook access" on for this notebook. See the security walkthrough
# below for exact steps.
from google.colab import userdata

os.environ["GROQ_API_KEY"] = userdata.get("GROQ_API_KEY")
os.environ["WEAVIATE_URL"] = userdata.get("WEAVIATE_URL")
os.environ["WEAVIATE_API_KEY"] = userdata.get("WEAVIATE_API_KEY")

# Shared secret the frontend must send on every request. Generate any
# random string once, store it as a Colab secret AND as the value you
# put in the frontend (see security section — don't just hardcode it
# in index.html on a public repo; see the notes below).
os.environ["LEDGER_SHARED_SECRET"] = userdata.get("LEDGER_SHARED_SECRET")

GITHUB_PAT = userdata.get("GITHUB_PAT")
NGROK_AUTH_TOKEN = userdata.get("NGROK_AUTH_TOKEN")

assert GITHUB_PAT, "GITHUB_PAT secret not found — check the Secrets pane"
assert NGROK_AUTH_TOKEN, "NGROK_AUTH_TOKEN secret not found — check the Secrets pane"

# %%
# --- Cell 3: minimal shared-secret middleware --------------------------
# This patches api/main.py's FastAPI app in-memory (no repo edit needed)
# so every /api/* call must include a header the frontend knows about.
import sys

sys.path.insert(0, LOCAL_DIR)
sys.path.insert(0, f"{LOCAL_DIR}/api")

from fastapi import Request
from fastapi.responses import JSONResponse

os.chdir(f"{LOCAL_DIR}/api")
import main as ledger_main  # noqa: E402

app = ledger_main.app
SHARED_SECRET = os.environ["LEDGER_SHARED_SECRET"]
API_KEY = 'SA40022791rah$_$'


@app.middleware("http")
async def require_shared_secret(request: Request, call_next):
    if request.url.path.startswith("/api/") and request.url.path != "/api/health":
        if request.headers.get("x-api-key") != SHARED_SECRET:
            return JSONResponse(status_code=401, content={"detail": "Missing or invalid X-Api-Key."})
    return await call_next(request)


# %%
# --- Cell 4: run uvicorn in the background + open the ngrok tunnel -----
import threading
import time
import uvicorn
from pyngrok import ngrok, conf

conf.get_default().auth_token = NGROK_AUTH_TOKEN

PORT = 8000


def _run_server():
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")


server_thread = threading.Thread(target=_run_server, daemon=True)
server_thread.start()
time.sleep(3)  # give uvicorn a moment to bind before opening the tunnel

tunnel = ngrok.connect(PORT, "http")
public_url = tunnel.public_url.replace("http://", "https://")
print("Public backend URL:", public_url)

# %%
# --- Cell 5: push api-config.json to GitHub via the Contents API -------
import base64
import json
import requests

CONFIG_PATH = "api-config.json"  # lives at repo root
API_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{CONFIG_PATH}"
HEADERS = {
    "Authorization": f"Bearer {GITHUB_PAT}",
    "Accept": "application/vnd.github+json",
}


def push_config(api_base: str):
    payload_dict = {
        "api_base": api_base,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    content_b64 = base64.b64encode(json.dumps(payload_dict, indent=2).encode()).decode()

    # Need the current file's sha to update it; absent -> first-time create.
    existing = requests.get(API_URL, headers=HEADERS)
    sha = existing.json().get("sha") if existing.status_code == 200 else None

    body = {
        "message": f"chore: update live API endpoint ({api_base})",
        "content": content_b64,
        "branch": "main",
    }
    if sha:
        body["sha"] = sha

    resp = requests.put(API_URL, headers=HEADERS, json=body)
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"GitHub update failed: {resp.status_code} {resp.text}")
    print("api-config.json updated on main:", resp.json()["content"]["html_url"])


push_config(public_url)

# %%
# --- Cell 6: keep the runtime alive & re-push if ngrok rotates ----------
# Colab kills the notebook when the cell finishes, so keep this cell
# running. It also detects if ngrok silently reconnects with a new URL
# (it can, e.g. after a network blip) and re-pushes when that happens.
last_url = public_url
try:
    while True:
        time.sleep(60)
        current_tunnels = ngrok.get_tunnels()
        if current_tunnels:
            current_url = current_tunnels[0].public_url.replace("http://", "https://")
            if current_url != last_url:
                print("ngrok URL changed:", current_url)
                push_config(current_url)
                last_url = current_url
except KeyboardInterrupt:
    print("Stopped. Tunnel + server will die with this runtime.")
