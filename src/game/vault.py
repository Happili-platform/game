# SPDX-License-Identifier: AGPL-3.0-only
"""Local encrypted credential vault for localhost development.

SQLite contains AES-256-GCM ciphertext only. The 256-bit master key lives in a
separate, user-readable-only file (or an explicitly configured environment var).
This is NOT an enterprise credential manager: it lacks KMS, rotation, per-tenant keys and production-grade vault controls.
"""
from __future__ import annotations

import base64
import json
import os
import stat
from pathlib import Path
from secrets import token_bytes

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class VaultError(Exception):
    """Safe-to-display local key/decryption issue (never includes secret content)."""


def key_path() -> Path:
    return Path(os.getenv('GAME_VAULT_KEY_PATH', '~/.config/game/master.key')).expanduser()


def _decode_key(text: bytes) -> bytes:
    try:
        raw = base64.b64decode(text.strip(), altchars=b'-_', validate=True)
    except Exception:
        raise VaultError('Invalid local vault master key encoding') from None
    if len(raw) != 32:
        raise VaultError('Local vault master key must be 32 bytes')
    return raw


def master_key(*, create: bool = False, has_saved_credentials: bool = False) -> bytes:
    supplied = os.getenv('GAME_MASTER_KEY')
    if supplied:
        try:
            return _decode_key(supplied.encode('ascii', 'strict'))
        except UnicodeEncodeError:
            raise VaultError('Invalid local vault master key encoding') from None
    path = key_path()
    try:
        file_stat = path.lstat()
    except FileNotFoundError:
        if not create:
            raise VaultError('Local credential vault key is missing; restore the original key file') from None
        if has_saved_credentials:
            raise VaultError('Saved credentials exist but vault key is missing; restore the original key before saving')
        # A separate master-key file is created outside the source tree; use
        # exclusive create and restrictive permissions, never overwrite it.
        try:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, 'O_NOFOLLOW'):
                flags |= os.O_NOFOLLOW
            fd = os.open(path, flags, 0o600)
        except FileExistsError:
            return master_key(create=False)
        except OSError:
            raise VaultError('Could not create local credential vault key file') from None
        key = token_bytes(32)
        with os.fdopen(fd, 'wb') as out:
            out.write(base64.urlsafe_b64encode(key) + b'\n')
            out.flush()
            os.fsync(out.fileno())
        return key
    except OSError:
        raise VaultError('Could not access local credential vault key file') from None
    if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_mode & 0o077:
        raise VaultError('Vault key must be a regular file readable only by its owner (chmod 600)')
    try:
        return _decode_key(path.read_bytes())
    except OSError:
        raise VaultError('Could not read local credential vault key file') from None


def _aad(connection_id: str, provider: str) -> bytes:
    return f'GAME:v1:{connection_id}:{provider}'.encode('utf-8')


def encrypt(connection_id: str, provider: str, credentials: dict,
            *, has_saved_credentials: bool) -> str:
    key = master_key(create=True, has_saved_credentials=has_saved_credentials)
    data = json.dumps(credentials, separators=(',', ':'), ensure_ascii=True).encode('utf-8')
    nonce = token_bytes(12)
    ciphertext = AESGCM(key).encrypt(nonce, data, _aad(connection_id, provider))
    return base64.urlsafe_b64encode(nonce + ciphertext).decode('ascii')


def decrypt(connection_id: str, provider: str, ciphertext_b64: str) -> dict:
    key = master_key()
    try:
        payload = base64.b64decode(ciphertext_b64, altchars=b'-_', validate=True)
        if len(payload) < 29:
            raise ValueError('Invalid length')
        data = AESGCM(key).decrypt(payload[:12], payload[12:], _aad(connection_id, provider))
        result = json.loads(data)
        if not isinstance(result, dict):
            raise ValueError('Not an object')
        return result
    except (InvalidTag, ValueError, TypeError, json.JSONDecodeError):
        raise VaultError('Saved credentials cannot be decrypted; verify original master key and database') from None
