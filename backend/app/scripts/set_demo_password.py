"""
One-time secure setup: set a password on the existing demo@securedapp.io
admin account for local E2E login verification.

Reads the password from the DEMO_PASSWORD environment variable. If not set,
generates a strong random password and writes it to DEMO_PASSWORD_FILE so the
operator can retrieve it. Never prints the password to stdout/stderr.

Usage (from backend directory):
    set DEMO_PASSWORD=<your-password>
    python -m scripts.set_demo_password
"""
import os
import secrets
import string
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.user import User

DEMO_EMAIL = "demo@securedapp.io"
PASSWORD_FILE = os.path.join(os.path.dirname(__file__), "..", "DEMO_PASSWORD.recovered")


def main() -> None:
    password = os.environ.get("DEMO_PASSWORD")
    if not password:
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        password = "".join(secrets.choice(alphabet) for _ in range(20))
        # Write the generated password to a file the operator can read.
        with open(PASSWORD_FILE, "w") as f:
            f.write(password)
        print(f"No DEMO_PASSWORD set. Generated password written to {PASSWORD_FILE}")
    else:
        if len(password) < 8:
            print("Error: password must be at least 8 characters.", file=sys.stderr)
            sys.exit(1)

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == DEMO_EMAIL).first()
        if user is None:
            print(f"Error: user {DEMO_EMAIL} not found.", file=sys.stderr)
            sys.exit(1)
        user.password_hash = hash_password(password)
        # Ensure account is active and not locked.
        user.active = True
        user.failed_login_attempts = 0
        user.locked_until = None
        db.add(user)
        db.commit()
        print(
            f"Password set for {DEMO_EMAIL} (id={user.id}, role={user.role}). "
            "Account is active and unlocked."
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
