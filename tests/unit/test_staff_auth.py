"""Unit tests for staff authentication utilities."""



from datasette_suggest_purchase.staff_auth import (
    authenticate_staff,
    get_staff_account,
    hash_password,
    sync_admin_from_env,
    upsert_staff_account,
    verify_password,
)


class TestPasswordHashing:
    """Tests for password hashing and verification."""

    def test_hash_password_format(self):
        """Hash should be in pbkdf2_sha256$iterations$salt$hash format."""
        password_hash = hash_password("testpassword")
        parts = password_hash.split("$")

        assert len(parts) == 4
        assert parts[0] == "pbkdf2_sha256"
        assert int(parts[1]) > 0  # iterations
        assert len(parts[2]) == 32  # salt (16 bytes = 32 hex chars)
        assert len(parts[3]) == 64  # hash (32 bytes = 64 hex chars)

    def test_hash_password_unique_salts(self):
        """Each hash should have a unique salt."""
        hash1 = hash_password("password")
        hash2 = hash_password("password")

        # Same password should produce different hashes due to random salt
        assert hash1 != hash2

    def test_verify_password_correct(self):
        """Correct password should verify."""
        password = "mysecretpassword"
        password_hash = hash_password(password)

        assert verify_password(password, password_hash) is True

    def test_verify_password_incorrect(self):
        """Incorrect password should not verify."""
        password_hash = hash_password("correctpassword")

        assert verify_password("wrongpassword", password_hash) is False

    def test_verify_password_invalid_hash_format(self):
        """Invalid hash format should return False."""
        assert verify_password("password", "invalid") is False
        assert verify_password("password", "too$few$parts") is False
        assert verify_password("password", "wrong_prefix$100$salt$hash") is False

    def test_verify_password_empty_inputs(self):
        """Empty inputs should not crash."""
        assert verify_password("", hash_password("password")) is False
        assert verify_password("password", "") is False


class TestStaffAccountOperations:
    """Tests for staff account database operations."""

    def test_upsert_creates_account(self, db_path):
        """Upserting a new account creates it."""
        upsert_staff_account(db_path, "newuser", hash_password("pass123"), "New User")

        account = get_staff_account(db_path, "newuser")
        assert account is not None
        assert account["username"] == "newuser"
        assert account["display_name"] == "New User"
        assert verify_password("pass123", account["password_hash"])

    def test_upsert_updates_existing_account(self, db_path):
        """Upserting an existing account updates it."""
        # Create initial account
        upsert_staff_account(db_path, "admin", hash_password("oldpass"), "Admin")

        # Update with new password
        upsert_staff_account(db_path, "admin", hash_password("newpass"), "Administrator")

        account = get_staff_account(db_path, "admin")
        assert account["display_name"] == "Administrator"
        assert verify_password("newpass", account["password_hash"])
        assert not verify_password("oldpass", account["password_hash"])

    def test_get_staff_account_not_found(self, db_path):
        """Getting a non-existent account returns None."""
        account = get_staff_account(db_path, "nonexistent")
        assert account is None

    def test_get_staff_account_db_not_exists(self, tmp_path):
        """Getting account from non-existent DB returns None."""
        fake_path = tmp_path / "nonexistent.db"
        account = get_staff_account(fake_path, "admin")
        assert account is None


class TestAuthentication:
    """Tests for staff authentication."""

    def test_authenticate_success(self, db_path):
        """Successful authentication returns account."""
        upsert_staff_account(db_path, "testuser", hash_password("testpass"), "Test User")

        account = authenticate_staff(db_path, "testuser", "testpass")
        assert account is not None
        assert account["username"] == "testuser"

    def test_authenticate_wrong_password(self, db_path):
        """Wrong password returns None."""
        upsert_staff_account(db_path, "testuser", hash_password("testpass"), "Test User")

        account = authenticate_staff(db_path, "testuser", "wrongpass")
        assert account is None

    def test_authenticate_nonexistent_user(self, db_path):
        """Non-existent user returns None."""
        account = authenticate_staff(db_path, "nouser", "anypass")
        assert account is None


class TestEnvSync:
    """Tests for syncing admin from environment variables."""

    def test_sync_creates_admin(self, db_path, monkeypatch):
        """Syncing with env vars creates admin account."""
        monkeypatch.setenv("STAFF_ADMIN_PASSWORD", "envpassword")
        monkeypatch.setenv("STAFF_ADMIN_DISPLAY_NAME", "Env Admin")

        result = sync_admin_from_env(db_path)
        assert result is True

        account = get_staff_account(db_path, "admin")
        assert account is not None
        assert account["display_name"] == "Env Admin"
        assert verify_password("envpassword", account["password_hash"])

    def test_sync_custom_username(self, db_path, monkeypatch):
        """Syncing with custom username creates correct account."""
        monkeypatch.setenv("STAFF_ADMIN_USERNAME", "superadmin")
        monkeypatch.setenv("STAFF_ADMIN_PASSWORD", "superpass")

        sync_admin_from_env(db_path)

        account = get_staff_account(db_path, "superadmin")
        assert account is not None
        assert verify_password("superpass", account["password_hash"])

    def test_sync_no_password_skips(self, db_path, monkeypatch):
        """Syncing without password env var skips account creation."""
        # Ensure no password is set
        monkeypatch.delenv("STAFF_ADMIN_PASSWORD", raising=False)

        result = sync_admin_from_env(db_path)
        assert result is False

        account = get_staff_account(db_path, "admin")
        assert account is None

    def test_sync_updates_existing(self, db_path, monkeypatch):
        """Syncing updates existing admin account."""
        # Create initial account
        upsert_staff_account(db_path, "admin", hash_password("oldpass"), "Old Admin")

        # Sync with new password
        monkeypatch.setenv("STAFF_ADMIN_PASSWORD", "newpass")
        monkeypatch.setenv("STAFF_ADMIN_DISPLAY_NAME", "New Admin")

        sync_admin_from_env(db_path)

        account = get_staff_account(db_path, "admin")
        assert account["display_name"] == "New Admin"
        assert verify_password("newpass", account["password_hash"])
