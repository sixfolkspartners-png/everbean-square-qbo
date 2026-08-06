"""
Persist the rotating QuickBooks refresh token back into a GitHub Actions secret,
so the daily job survives Intuit's ~100-day refresh-token rotation with no
manual re-auth.

Requires (as repo secrets):
  GH_TOKEN        - a fine-grained PAT with 'Secrets: read/write' on this repo
  GH_REPO         - "owner/repo"
It updates the repo secret named QBO_REFRESH_TOKEN in place.

If GH_TOKEN / GH_REPO are absent (e.g. running locally), this is a no-op and the
new token is just logged so you can update it by hand.
"""
from __future__ import annotations
import os
import base64
import requests

try:
    from nacl import public, encoding  # pynacl, for GitHub secret encryption
    HAVE_NACL = True
except Exception:
    HAVE_NACL = False


def persist_refresh_token(new_token: str) -> None:
    gh_token = os.environ.get("GH_TOKEN")
    repo = os.environ.get("GH_REPO")
    if not (gh_token and repo):
        print("[token_store] GH_TOKEN/GH_REPO not set — not persisting. "
              "New refresh token (store it manually):", new_token[:8] + "...")
        return
    if not HAVE_NACL:
        raise RuntimeError("pynacl required to update GitHub secrets")

    h = {"Authorization": f"Bearer {gh_token}",
         "Accept": "application/vnd.github+json"}
    # 1) get the repo public key
    pk = requests.get(f"https://api.github.com/repos/{repo}/actions/secrets/public-key",
                      headers=h, timeout=30).json()
    # 2) encrypt the value with libsodium sealed box
    pub = public.PublicKey(pk["key"].encode(), encoding.Base64Encoder())
    sealed = public.SealedBox(pub).encrypt(new_token.encode())
    enc_value = base64.b64encode(sealed).decode()
    # 3) upsert the secret
    r = requests.put(
        f"https://api.github.com/repos/{repo}/actions/secrets/QBO_REFRESH_TOKEN",
        headers=h, timeout=30,
        json={"encrypted_value": enc_value, "key_id": pk["key_id"]})
    r.raise_for_status()
    print("[token_store] QBO_REFRESH_TOKEN secret rotated successfully.")
