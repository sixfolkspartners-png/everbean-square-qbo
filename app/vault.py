"""Token vault — encrypt OAuth refresh tokens at rest with Fernet (symmetric).

The key comes from env DAILYLEDGER_FERNET_KEY (generate once with
`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`).
Never store plaintext tokens in the DB; only the encrypted blob.
"""
from __future__ import annotations
import os, base64, hashlib
from cryptography.fernet import Fernet

_key = os.environ.get("DAILYLEDGER_FERNET_KEY")
# Dev fallback: a deterministic, VALID Fernet key so local runs work without
# setup. NEVER use in production — set DAILYLEDGER_FERNET_KEY there.
_DEV_KEY = base64.urlsafe_b64encode(hashlib.sha256(b"dailyledger-dev").digest()).decode()
_fernet = Fernet((_key or _DEV_KEY).encode())


def encrypt(plaintext: str) -> str:
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet.decrypt(token.encode()).decode()


def using_dev_key() -> bool:
    return not _key
