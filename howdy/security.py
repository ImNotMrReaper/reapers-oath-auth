"""
Howdy Biometric Security & Cryptographic Key Management Engine
Standard: AES-256-GCM Authenticated Encryption with Associated Data (AEAD)
Compression: XZ (LZMA2 Preset 6 / Extreme)
Key Derivation: HKDF-SHA256 with /etc/machine-id hardware binding
"""

import os
import sys
import json
import lzma
import zlib
import secrets
import stat
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

HOWDY_DIR = "/lib/security/howdy"
KEY_FILE = os.path.join(HOWDY_DIR, "security.key")
MACHINE_ID_FILE = "/etc/machine-id"

MAGIC_HEADER_V1 = b"HOWDY_ENC_V1\x00"
MAGIC_HEADER_ZLIB_V2 = b"HOWDY_ENC_ZLIB_V2\x00"
MAGIC_HEADER_XZ_V3 = b"HOWDY_ENC_XZ_V3\x00"
MAGIC_HEADER = MAGIC_HEADER_XZ_V3  # Default active standard


def _get_or_create_master_key() -> bytes:
    """Retrieve or generate the 256-bit cryptographically secure master key"""
    if os.path.exists(KEY_FILE):
        try:
            with open(KEY_FILE, "rb") as f:
                key = f.read().strip()
                if len(key) == 32:
                    return key
        except Exception:
            pass

    # Generate new random 32-byte (256-bit) secret
    new_key = secrets.token_bytes(32)
    tmp_file = KEY_FILE + ".tmp"
    with open(tmp_file, "wb") as f:
        f.write(new_key)
    os.chmod(tmp_file, stat.S_IRUSR)  # 0400 - read-only for root
    os.replace(tmp_file, KEY_FILE)
    return new_key


def _get_cipher() -> AESGCM:
    """Derive machine-unique AES-256-GCM cipher bound to this hardware"""
    master_key = _get_or_create_master_key()
    mach_id = b"default_machine_salt"
    if os.path.exists(MACHINE_ID_FILE):
        try:
            with open(MACHINE_ID_FILE, "rb") as f:
                mach_id = f.read().strip()
        except Exception:
            pass

    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"howdy_biometric_salt_v1",
        info=b"howdy_face_aes256_gcm"
    )
    derived_key = hkdf.derive(master_key + b":" + mach_id)
    return AESGCM(derived_key)


def load_user_models(user: str) -> list:
    """Load, decrypt (AES-256-GCM), and decompress (XZ/LZMA2) user face models from disk"""
    model_path = os.path.join(HOWDY_DIR, "models", f"{user}.dat")
    if not os.path.exists(model_path):
        return []

    with open(model_path, "rb") as f:
        payload = f.read()

    if not payload:
        return []

    # 1. Active Standard: AES-256-GCM + XZ (LZMA2)
    if payload.startswith(MAGIC_HEADER_XZ_V3):
        try:
            cipher = _get_cipher()
            header_len = len(MAGIC_HEADER_XZ_V3)
            nonce = payload[header_len:header_len + 12]
            ciphertext = payload[header_len + 12:]
            decrypted = cipher.decrypt(nonce, ciphertext, None)
            decompressed = lzma.decompress(decrypted)
            return json.loads(decompressed.decode("utf-8"))
        except Exception as e:
            print(f"[Security Error] Failed to decrypt/decompress XZ V3 face models for {user}: {e}", file=sys.stderr)
            return []

    # 2. Backward Compatibility: AES-256-GCM + ZLIB
    elif payload.startswith(MAGIC_HEADER_ZLIB_V2):
        try:
            cipher = _get_cipher()
            header_len = len(MAGIC_HEADER_ZLIB_V2)
            nonce = payload[header_len:header_len + 12]
            ciphertext = payload[header_len + 12:]
            decrypted = cipher.decrypt(nonce, ciphertext, None)
            decompressed = zlib.decompress(decrypted)
            models = json.loads(decompressed.decode("utf-8"))
            try:
                save_user_models(user, models)  # Transparently upgrade to XZ on disk
            except Exception:
                pass
            return models
        except Exception as e:
            print(f"[Security Error] Failed to decrypt ZLIB V2 face models for {user}: {e}", file=sys.stderr)
            return []

    # 3. Backward Compatibility: AES-256-GCM Uncompressed (V1)
    elif payload.startswith(MAGIC_HEADER_V1):
        try:
            cipher = _get_cipher()
            header_len = len(MAGIC_HEADER_V1)
            nonce = payload[header_len:header_len + 12]
            ciphertext = payload[header_len + 12:]
            decrypted = cipher.decrypt(nonce, ciphertext, None)
            models = json.loads(decrypted.decode("utf-8"))
            try:
                save_user_models(user, models)  # Transparently upgrade to XZ on disk
            except Exception:
                pass
            return models
        except Exception as e:
            print(f"[Security Error] Failed to decrypt V1 face models for {user}: {e}", file=sys.stderr)
            return []

    # 4. Legacy Plaintext JSON
    else:
        try:
            models = json.loads(payload.decode("utf-8"))
            try:
                save_user_models(user, models)  # Transparently upgrade to XZ on disk
            except Exception:
                pass
            return models
        except Exception:
            return []


def save_user_models(user: str, models: list) -> None:
    """Compress with XZ (LZMA2) and encrypt with AES-256-GCM, atomically saving to disk"""
    models_dir = os.path.join(HOWDY_DIR, "models")
    os.makedirs(models_dir, exist_ok=True)
    model_path = os.path.join(models_dir, f"{user}.dat")

    cipher = _get_cipher()
    raw_data = json.dumps(models).encode("utf-8")
    compressed = lzma.compress(raw_data, preset=6)
    nonce = os.urandom(12)
    ciphertext = cipher.encrypt(nonce, compressed, None)
    payload = MAGIC_HEADER_XZ_V3 + nonce + ciphertext

    tmp_path = model_path + ".tmp"
    with open(tmp_path, "wb") as f:
        f.write(payload)

    # Set permissions: 0644 - root read/write, world read (protected by AES-256-GCM AEAD encryption)
    os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
    os.replace(tmp_path, model_path)
