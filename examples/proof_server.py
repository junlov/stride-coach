"""Run the CLI server inside a disposable PostgreSQL schema for mobile proof."""

from synthetic_database import synthetic_database

from stride_coach.cli import app

if __name__ == "__main__":
    with synthetic_database():
        app()
