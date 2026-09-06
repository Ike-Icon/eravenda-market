"""Run checked-in, idempotent SQL migrations before starting the web service."""

from pathlib import Path

from .database import engine


def run_migrations() -> None:
    migrations_dir = Path(__file__).resolve().parent.parent / "migrations"
    with engine.begin() as connection:
        # Migrations use ADD COLUMN IF NOT EXISTS, so applying them at each
        # deploy is safe and keeps Render's managed database in sync.
        for migration in sorted(migrations_dir.glob("*.sql")):
            connection.exec_driver_sql(migration.read_text())
            print(f"Applied migration: {migration.name}")


if __name__ == "__main__":
    run_migrations()
