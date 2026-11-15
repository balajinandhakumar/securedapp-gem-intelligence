"""
Secure initial administrator bootstrap.

Usage:

    # From the backend directory:
    python -m app.scripts.create_admin \
        --email admin@securedapp.io \
        --name "Platform Administrator" \
        --password '<strong-password>'

This command creates the first ADMIN user only if no users exist yet.
It does NOT create a default or hardcoded administrator account. If users
already exist (e.g. after a migration), the command is a no-op and exits
with a message, preventing accidental creation of a second admin or
overwriting an existing bootstrap.

The password must be supplied on the command line (or via the
--password-env option naming an environment variable). It is never echoed
and never written to any log or configuration file.
"""

import argparse
import getpass
import os
import sys
from typing import Optional

# Ensure the backend package is importable when run as a script.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.core.database import SessionLocal, engine, Base
from app.core.security import hash_password
from app.models.user import User


def bootstrap_admin(
    email: str,
    name: str,
    password: str,
    role: str = "admin",
) -> Optional[User]:
    """Create the initial administrator if no users exist.

    Returns the created User, or None if users already exist (no-op).
    Raises ValueError if the password is too short.
    """
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")

    db = SessionLocal()
    try:
        existing = db.query(User).first()
        if existing is not None:
            print(
                f"Bootstrap skipped: {db.query(User).count()} user(s) already exist. "
                "No default administrator was created.",
            )
            return None

        user = User(
            email=email.lower().strip(),
            name=name.strip(),
            password_hash=hash_password(password),
            role=role,
            active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        print(
            f"Initial administrator created: id={user.id} email={user.email} "
            f"role={user.role}",
        )
        return user
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bootstrap the initial SecuredApp administrator account.",
    )
    parser.add_argument("--email", required=True, help="Administrator email address.")
    parser.add_argument("--name", required=True, help="Administrator display name.")
    parser.add_argument(
        "--password",
        help="Administrator password (min 8 chars). If omitted, you will be prompted.",
    )
    parser.add_argument(
        "--password-env",
        help="Name of an environment variable containing the password.",
    )
    parser.add_argument(
        "--role",
        default="admin",
        choices=["admin", "operator", "viewer"],
        help="Role to assign (default: admin).",
    )
    args = parser.parse_args()

    # Resolve the password from the most explicit source available.
    password: Optional[str] = args.password
    if password is None and args.password_env:
        password = os.environ.get(args.password_env)
        if password is None:
            print(f"Error: environment variable {args.password_env} is not set.")
            sys.exit(1)
    if password is None:
        password = getpass.getpass("Enter administrator password: ")
        confirm = getpass.getpass("Confirm administrator password: ")
        if password != confirm:
            print("Error: passwords do not match.")
            sys.exit(1)

    try:
        bootstrap_admin(email=args.email, name=args.name, password=password, role=args.role)
    except ValueError as exc:
        print(f"Error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
