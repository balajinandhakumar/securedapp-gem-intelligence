import hashlib
import hmac
import secrets


def hash_password(password: str) -> str:
    """Hash password using PBKDF2 HMAC SHA256."""
    salt = secrets.token_bytes(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
    return f"{salt.hex()}${key.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    """Verify password against stored hash."""
    try:
        salt_hex, key_hex = password_hash.split("$")
        salt = bytes.fromhex(salt_hex)
        expected_key = bytes.fromhex(key_hex)
        computed_key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
        return hmac.compare_digest(expected_key, computed_key)
    except Exception:
        return False
