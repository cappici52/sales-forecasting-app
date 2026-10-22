"""Create a local PostgreSQL connection secret without printing it.

Run once from backend/. The generated .env is ignored by Git. This script does
not change PostgreSQL; create the matching login role and databases separately.
"""
from pathlib import Path
import secrets


def main() -> None:
    destination = Path(__file__).resolve().parents[1] / ".env"
    if destination.exists():
        raise SystemExit("backend/.env already exists; refusing to overwrite it")
    password = secrets.token_urlsafe(32)
    destination.write_text(
        "DATABASE_URL=postgresql+psycopg://projecta1:"
        f"{password}@127.0.0.1:5432/projecta1\n"
        "CORS_ORIGINS=http://localhost:3000,http://localhost:3001\n"
        "COOKIE_SECURE=false\n",
        encoding="utf-8",
    )
    print("Created backend/.env for the local projecta1 database; password was not printed.")


if __name__ == "__main__":
    main()
