"""Prepare an existing archive database before starting API and collector."""
import argparse
from pathlib import Path

from .db import db_path, migrate_live


def main():
    parser = argparse.ArgumentParser(description='Add Calcmula tables to an existing imported database.')
    parser.add_argument('--db', type=Path, default=db_path())
    args = parser.parse_args()
    migrate_live(args.db)
    print('Database ready: schema version 3', flush=True)


if __name__ == '__main__':
    main()
