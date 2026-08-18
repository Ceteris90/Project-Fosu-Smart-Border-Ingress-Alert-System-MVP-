"""Create or rotate Project Fosu dashboard credentials."""
import argparse
import base64
import getpass
import hashlib
import secrets
from pathlib import Path

from dotenv import set_key

SOURCE_ROOT = Path(__file__).resolve().parent.parent
REPOSITORY_ROOT = (
    SOURCE_ROOT.parent if SOURCE_ROOT.name == "1-app-source-code" else SOURCE_ROOT
)
ENV_PATH = REPOSITORY_ROOT / ".env"


def hash_password(password):
    salt = secrets.token_bytes(16)
    n, r, p = 2**14, 8, 1
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=n, r=r, p=p
    )
    encoded_salt = base64.urlsafe_b64encode(salt).decode("ascii")
    encoded_digest = base64.urlsafe_b64encode(digest).decode("ascii")
    return f"scrypt${n}${r}${p}${encoded_salt}${encoded_digest}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", default="fosu.admin")
    args = parser.parse_args()

    password = getpass.getpass("New dashboard password: ")
    confirmation = getpass.getpass("Confirm dashboard password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match.")
    if len(password) < 12:
        raise SystemExit("Password must contain at least 12 characters.")

    ENV_PATH.touch(mode=0o600, exist_ok=True)
    ENV_PATH.chmod(0o600)
    set_key(ENV_PATH, "FOSU_DASHBOARD_USERNAME", args.username, quote_mode="always")
    set_key(
        ENV_PATH,
        "FOSU_DASHBOARD_PASSWORD_HASH",
        hash_password(password),
        quote_mode="always",
    )
    print(f"Updated dashboard credentials for {args.username}. Reload the login page.")


if __name__ == "__main__":
    main()
