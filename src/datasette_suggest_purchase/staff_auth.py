"""
Staff authentication utilities for datasette-suggest-purchase.

Uses PBKDF2-SHA256 hashing (same as datasette-auth-passwords) for password security.
Supports syncing admin account from environment variables on startup.
"""

import hashlib
import os
import secrets
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

# PBKDF2 parameters (matching datasette-auth-passwords defaults)
HASH_ALGORITHM = "sha256"
HASH_ITERATIONS = 260000
HASH_SALT_LENGTH = 16
HASH_KEY_LENGTH = 32


def hash_password(password: str) -> str:
    """
    Hash a password using PBKDF2-SHA256.

    Returns a string in the format: pbkdf2_sha256$iterations$salt$hash
    This format is compatible with datasette-auth-passwords.
    """
    salt = secrets.token_hex(HASH_SALT_LENGTH)
    key = hashlib.pbkdf2_hmac(
        HASH_ALGORITHM,
        password.encode("utf-8"),
        salt.encode("utf-8"),
        HASH_ITERATIONS,
        dklen=HASH_KEY_LENGTH,
    )
    hash_hex = key.hex()
    return f"pbkdf2_{HASH_ALGORITHM}${HASH_ITERATIONS}${salt}${hash_hex}"


def verify_password(password: str, password_hash: str) -> bool:
    """
    Verify a password against a stored hash.

    Returns True if the password matches, False otherwise.
    """
    try:
        parts = password_hash.split("$")
        if len(parts) != 4:
            return False

        algorithm_part, iterations_str, salt, stored_hash = parts

        if not algorithm_part.startswith("pbkdf2_"):
            return False

        algorithm = algorithm_part[7:]  # Remove "pbkdf2_" prefix
        iterations = int(iterations_str)

        # Compute hash with same parameters
        key = hashlib.pbkdf2_hmac(
            algorithm,
            password.encode("utf-8"),
            salt.encode("utf-8"),
            iterations,
            dklen=len(bytes.fromhex(stored_hash)),
        )

        return secrets.compare_digest(key.hex(), stored_hash)

    except (ValueError, AttributeError):
        return False


def get_staff_account(db_path: Path, username: str) -> dict | None:
    """
    Get a staff account by username.

    Returns dict with username, password_hash, display_name or None if not found.
    """
    if not db_path.exists():
        return None

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            "SELECT username, password_hash, display_name FROM staff_accounts WHERE username = ?",
            (username,),
        )
        row = cursor.fetchone()
        if row:
            return {
                "username": row[0],
                "password_hash": row[1],
                "display_name": row[2],
            }
        return None
    finally:
        conn.close()


def upsert_staff_account(
    db_path: Path,
    username: str,
    password_hash: str,
    display_name: str | None = None,
) -> None:
    """
    Create or update a staff account.

    If the account exists, updates the password_hash and display_name.
    If it doesn't exist, creates a new account.
    """
    conn = sqlite3.connect(db_path)
    now = datetime.now(UTC).isoformat()

    try:
        # Check if account exists
        cursor = conn.execute(
            "SELECT username FROM staff_accounts WHERE username = ?",
            (username,),
        )
        exists = cursor.fetchone() is not None

        if exists:
            conn.execute(
                """
                UPDATE staff_accounts
                SET password_hash = ?, display_name = ?, updated_ts = ?
                WHERE username = ?
                """,
                (password_hash, display_name, now, username),
            )
        else:
            conn.execute(
                """
                INSERT INTO staff_accounts (username, password_hash, display_name, created_ts)
                VALUES (?, ?, ?, ?)
                """,
                (username, password_hash, display_name, now),
            )
        conn.commit()
    finally:
        conn.close()


def sync_admin_from_env(db_path: Path, verbose: bool = False) -> bool:
    """
    Sync admin account from environment variables.

    Reads STAFF_ADMIN_USERNAME (default: "admin") and STAFF_ADMIN_PASSWORD.
    If STAFF_ADMIN_PASSWORD is set, hashes it and upserts the account.

    Returns True if an account was synced, False otherwise.
    """
    username = os.environ.get("STAFF_ADMIN_USERNAME", "admin")
    password = os.environ.get("STAFF_ADMIN_PASSWORD")
    display_name = os.environ.get("STAFF_ADMIN_DISPLAY_NAME", "Administrator")

    if not password:
        if verbose:
            print("  STAFF_ADMIN_PASSWORD not set, skipping admin account sync")
        return False

    # Hash the password
    password_hash = hash_password(password)

    # Upsert the account
    upsert_staff_account(db_path, username, password_hash, display_name)

    if verbose:
        print(f"  Synced staff admin account: {username}")

    return True


def authenticate_staff(db_path: Path, username: str, password: str) -> dict | None:
    """
    Authenticate a staff user with username and password.

    Returns the staff account dict on success, None on failure.
    """
    account = get_staff_account(db_path, username)
    if account is None:
        return None

    if verify_password(password, account["password_hash"]):
        return account

    return None
