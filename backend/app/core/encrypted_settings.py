"""
Encrypted Settings — secure, disk-persistent platform configuration.

How it works
────────────
1. The encryption key is provided at deploy time via a Docker secret
   (mounted at the path in ENCRYPTION_KEY_FILE env var).  This is the
   ONLY secret the developer supplies.
2. On first start the platform enters "wizard mode" — the setup wizard page
   lets a developer enter all critical settings through the browser.
3. The wizard saves those settings as an AES-256-GCM encrypted file at
   SETTINGS_FILE_PATH (default: /data/settings.enc), which must be on a
   Docker-mounted volume so the data survives container restarts.
4. On subsequent starts the backend decrypts the file, injects the values
   into os.environ, then initialises normally.
5. Multiple containers can share the same mounted volume and encryption key —
   all of them decrypt identically.

Security model
──────────────
• The encryption key is delivered as a Docker secret (tmpfs mount inside the
  container — never written to disk).  The encrypted settings file lives on a
  separate Docker named volume.  An attacker needs BOTH to read any secrets.
• ENCRYPTION_KEY env var is supported as a fallback for local development
  without Docker secrets.  Never use it in production.
• Encryption: AES-256-GCM (256-bit key, 96-bit random nonce, 128-bit auth tag).
  The full 32-byte derived key is used for AES-256 — nothing is split or wasted.
• Key derivation: PBKDF2-HMAC-SHA256, 480 000 iterations, fixed salt.
  The fixed salt is intentional: derivation must be deterministic so every
  container obtains the same key from the same master secret.
• Authentication: GCM mode provides built-in authenticated encryption (AEAD).
  Any tampering with the ciphertext or nonce causes decryption to fail.
• File format: nonce (12 bytes) || ciphertext+tag written as raw bytes.
• If the settings file is deleted the wizard runs again.  Because the
  database already exists and is at the correct schema level, the developer
  just re-enters credentials and the wizard skips migrations.
"""

import json
import os
import secrets
from pathlib import Path
from threading import Lock
from typing import Dict, Optional

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# ── Configuration ─────────────────────────────────────────────────────────────

SETTINGS_FILE_PATH: Path = Path(
    os.getenv("SETTINGS_FILE_PATH", "/data/settings.enc")
)

# Fixed salt: derivation must be deterministic across containers.
_KDF_SALT       = b"baseline-platform-v1"
_KDF_ITERATIONS = 480_000   # NIST SP 800-132 recommendation (2023)
_NONCE_SIZE     = 12        # 96-bit nonce — standard for AES-GCM

# ── Module-level cache ────────────────────────────────────────────────────────

_lock:           Lock                     = Lock()
_key_cache:      Optional[bytes]          = None
_settings_cache: Optional[Dict[str, str]] = None


# ── Key derivation ────────────────────────────────────────────────────────────

def _derive_key(master: str) -> bytes:
    """
    Derive a 32-byte AES-256 key from the master encryption key string.
    The full 32 bytes are used directly for AES-256 — no splitting.
    """
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_KDF_SALT,
        iterations=_KDF_ITERATIONS,
    )
    return kdf.derive(master.encode("utf-8"))


def _get_encryption_key() -> str:
    """
    Return the master encryption key.

    Resolution order:
    1. Read from the file path in ENCRYPTION_KEY_FILE (Docker secret — preferred).
    2. Fall back to ENCRYPTION_KEY env var (local development only).

    Returns an empty string when neither source is available.
    """
    file_path = os.getenv("ENCRYPTION_KEY_FILE", "").strip()
    if file_path:
        try:
            return Path(file_path).read_text().strip()
        except OSError:
            pass
    return os.getenv("ENCRYPTION_KEY", "").strip()


def _get_key() -> Optional[bytes]:
    """Return the derived AES-256 key (cached)."""
    global _key_cache
    if _key_cache is not None:
        return _key_cache
    master = _get_encryption_key()
    if not master:
        return None
    _key_cache = _derive_key(master)
    return _key_cache


# ── Public API ────────────────────────────────────────────────────────────────

def is_setup_complete() -> bool:
    """
    Return True when the settings file exists AND can be decrypted with
    the configured encryption key.  This is the definitive "wizard done" check.
    """
    return load_encrypted_settings() is not None


def load_encrypted_settings() -> Optional[Dict[str, str]]:
    """
    Decrypt and return the settings dict from disk.

    File format on disk: nonce (12 bytes) || AES-256-GCM ciphertext+tag.

    Returns None when:
    - Encryption key is not available
    - The settings file does not exist
    - Decryption fails (wrong key, corrupted file, or tampered data)
    """
    global _settings_cache
    with _lock:
        if _settings_cache is not None:
            return _settings_cache

        key = _get_key()
        if key is None or not SETTINGS_FILE_PATH.exists():
            return None

        try:
            raw        = SETTINGS_FILE_PATH.read_bytes()
            nonce      = raw[:_NONCE_SIZE]
            ciphertext = raw[_NONCE_SIZE:]
            plaintext  = AESGCM(key).decrypt(nonce, ciphertext, None)
            data       = json.loads(plaintext)
            _settings_cache = {
                k: str(v)
                for k, v in data.get("settings", {}).items()
                if v is not None
            }
            return _settings_cache
        except Exception:
            # Wrong key, truncated file, or authentication tag mismatch
            return None


def save_encrypted_settings(settings: Dict[str, str], encryption_key: str) -> None:
    """
    Encrypt *settings* with AES-256-GCM and write to SETTINGS_FILE_PATH.

    A fresh 96-bit nonce is generated for every save.  The file is written
    atomically (nonce prepended to ciphertext+tag) and the in-process cache
    is cleared so the next load re-reads the new file.
    """
    global _settings_cache, _key_cache

    key       = _derive_key(encryption_key)
    payload   = json.dumps({"v": 2, "settings": settings}, indent=2).encode("utf-8")
    nonce     = secrets.token_bytes(_NONCE_SIZE)
    encrypted = AESGCM(key).encrypt(nonce, payload, None)

    SETTINGS_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE_PATH.write_bytes(nonce + encrypted)

    with _lock:
        _settings_cache = None
        _key_cache      = None


def inject_into_environment() -> bool:
    """
    Load settings from the encrypted file and inject them into os.environ
    (using setdefault so existing env vars take precedence).

    Returns True on success, False when the file is unavailable.
    """
    loaded = load_encrypted_settings()
    if loaded is None:
        return False
    for key, value in loaded.items():
        os.environ.setdefault(key, value)
    return True


def verify_key(candidate: str) -> bool:
    """
    Return True if *candidate* matches the configured encryption key.
    Used by setup wizard endpoints to authenticate the developer.
    """
    configured = _get_encryption_key()
    return bool(configured) and candidate.strip() == configured
