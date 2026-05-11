"""
Password hashing and session token helpers. Owns all cryptographic
primitives used by the self-managed auth system:
  - bcrypt for password hashing/verification (via passlib)
  - secrets.token_urlsafe for opaque session token generation
  - SHA-256 for storing a safe digest of the session token in the DB
  - HMAC-SHA256 for tokenising card PANs (PCI DSS compliant lookup)
"""

import hashlib
import hmac
import secrets

import bcrypt


def hash_password(plain: str) -> str:
    """
    Return the bcrypt hash of a plain-text password.

    Args:
    ----
        plain: The raw password string supplied by the user.

    Returns:
    -------
        A bcrypt hash string suitable for storage in the database.

    """
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """
    Verify a plain-text password against a stored bcrypt hash.

    Args:
    ----
        plain: The raw password string supplied by the user.
        hashed: The bcrypt hash stored in the database.

    Returns:
    -------
        True if the password matches, False otherwise.

    """
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        return False


def generate_session_token() -> str:
    """
    Generate a cryptographically secure opaque session token.

    Returns
    -------
        A 256-bit URL-safe base64 token string. This value is returned to
        the client and must never be persisted directly in the database.

    """
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    """
    Return the SHA-256 hex digest of a session token for safe storage
    in the database if there is an attack not valid session tokens were leaked.

    Args:
    ----
        token: The raw session token string.

    Returns:
    -------
        64-character lowercase hex string (SHA-256 digest).

    """
    return hashlib.sha256(token.encode()).hexdigest()


def hmac_pan(number: str, key: str) -> str:
    """
    Return the HMAC-SHA256 hex digest of a card PAN for safe DB storage.
    The raw PAN is never persisted; only this digest is stored and used
    for lookup (get-or-create semantics on transaction creation).

    Args:
    ----
        number: Card number in XXXX-XXXX-XXXX-XXXX format (digits + hyphens).
        key: The PAN_HMAC_KEY secret from application settings.

    Returns:
    -------
        64-character lowercase hex string (HMAC-SHA256 digest).

    """
    # Normalise: strip hyphens so formatting differences don't create duplicates
    digits = number.replace("-", "")
    return hmac.new(key.encode(), digits.encode(), hashlib.sha256).hexdigest()
