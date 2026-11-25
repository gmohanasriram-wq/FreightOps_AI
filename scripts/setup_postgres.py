"""Automated local PostgreSQL 16 setup using official portable Windows binaries.

Does not require Docker or administrative privileges. Sets up an isolated
database cluster in freightops-ai/.postgres/ with user 'freightops' and database 'freightops'.
"""
import os
import sys
import socket
import zipfile
import urllib.request
import subprocess
import time
from pathlib import Path

PG_VERSION = "16.6-1"
ZIP_URL = f"https://get.enterprisedb.com/postgresql/postgresql-{PG_VERSION}-windows-x64-binaries.zip"

BASE_DIR = Path(__file__).resolve().parent.parent
PG_DIR = BASE_DIR / ".postgres"
BIN_DIR = PG_DIR / "pgsql" / "bin"
DATA_DIR = PG_DIR / "data"
LOG_FILE = PG_DIR / "postgres.log"
ZIP_PATH = PG_DIR / f"postgresql-{PG_VERSION}.zip"


def is_port_in_use(port: int = 5432) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        return s.connect_ex(("127.0.0.1", port)) == 0


def download_binaries():
    if (BIN_DIR / "postgres.exe").exists():
        print("PostgreSQL binaries already present in", BIN_DIR)
        return

    PG_DIR.mkdir(parents=True, exist_ok=True)
    if not ZIP_PATH.exists():
        print(f"Downloading PostgreSQL {PG_VERSION} portable binaries from {ZIP_URL}...")
        req = urllib.request.Request(ZIP_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as resp, open(ZIP_PATH, "wb") as out_file:
            total_size = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            block_size = 1024 * 1024  # 1MB
            last_print = time.time()
            while True:
                buffer = resp.read(block_size)
                if not buffer:
                    break
                out_file.write(buffer)
                downloaded += len(buffer)
                if time.time() - last_print > 3:
                    pct = (downloaded / total_size * 100) if total_size else 0
                    print(f"  Downloaded {downloaded / 1024 / 1024:.1f} MB ({pct:.1f}%)...")
                    last_print = time.time()
        print(f"Download complete: {downloaded / 1024 / 1024:.1f} MB saved to {ZIP_PATH.name}")

    print("Extracting PostgreSQL binaries...")
    with zipfile.ZipFile(ZIP_PATH, "r") as zip_ref:
        zip_ref.extractall(PG_DIR)
    print("Binaries extracted to", BIN_DIR)


def init_database():
    if (DATA_DIR / "PG_VERSION").exists():
        print("Database cluster already initialized in", DATA_DIR)
        return

    print("Initializing database cluster with user 'freightops'...")
    initdb_exe = BIN_DIR / "initdb.exe"
    cmd = [
        str(initdb_exe),
        "-U", "freightops",
        "-A", "trust",
        "-E", "UTF8",
        "-D", str(DATA_DIR),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print("initdb error:", res.stderr)
        sys.exit(1)
    print("Cluster initialized successfully.")


def start_database():
    if is_port_in_use(5432):
        print("Port 5432 is already open. PostgreSQL appears to be running.")
        return

    print("Starting PostgreSQL server on port 5432...")
    pg_ctl_exe = BIN_DIR / "pg_ctl.exe"
    cmd = [
        str(pg_ctl_exe),
        "start",
        "-D", str(DATA_DIR),
        "-l", str(LOG_FILE),
        "-w",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print("pg_ctl start output:", res.stdout, res.stderr)
        # Check if port opened anyway
        if not is_port_in_use(5432):
            print("Failed to start PostgreSQL. Check log:", LOG_FILE)
            sys.exit(1)
    print("PostgreSQL is running on port 5432.")


def create_freightops_db():
    createdb_exe = BIN_DIR / "createdb.exe"
    if not createdb_exe.exists():
        return
    cmd = [str(createdb_exe), "-U", "freightops", "-h", "127.0.0.1", "-p", "5432", "freightops"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if "already exists" in res.stderr or res.returncode == 0:
        print("Database 'freightops' is ready.")
    else:
        print("createdb note:", res.stderr.strip())


def verify_connection():
    psql_exe = BIN_DIR / "psql.exe"
    cmd = [str(psql_exe), "-U", "freightops", "-h", "127.0.0.1", "-p", "5432", "-d", "freightops", "-c", "SELECT version();"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0:
        print("\n=== Verification Successful ===")
        print(res.stdout.strip())
    else:
        print("Verification query error:", res.stderr)


if __name__ == "__main__":
    download_binaries()
    init_database()
    start_database()
    create_freightops_db()
    verify_connection()
