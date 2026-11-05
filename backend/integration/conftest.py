"""Disposable PostgreSQL integration fixtures; deliberately outside tests/conftest.py.

This emulates only auth.users/auth.uid and Storage SQL objects required to parse
our migrations. It is NOT a local/cloud Supabase installation.
"""
import contextlib
import fcntl
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from urllib.parse import quote
import uuid

import httpx
import jwt
import psycopg
from psycopg import sql
import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = Path(os.environ.get("JOBSEEKER_PG_RUNTIME", "/tmp/jobseeker-pg-validation-runtime"))
PG_BIN = RUNTIME / "pgsql/bin"
POSTGREST = RUNTIME / "postgrest/postgrest"
HISTORICAL_SCHEMA_COMMIT = "ec5e1bd8270947e3e02c13521c1b4716414bd698"
A = "10000000-0000-0000-0000-000000000001"
B = "20000000-0000-0000-0000-000000000002"
ISSUER = "http://127.0.0.1:54321"

BOOTSTRAP = """
create schema auth;
create table auth.users(id uuid primary key);
create function auth.uid() returns uuid language sql stable as $$
 select (nullif(current_setting('request.jwt.claims', true),'')::jsonb->>'sub')::uuid
$$;
create schema storage;
create table storage.buckets(id text primary key, name text, public boolean);
create table storage.objects(id uuid primary key default gen_random_uuid(), bucket_id text, name text);
create function storage.foldername(text) returns text[] language sql immutable as $$
 select (string_to_array($1,'/'))[1:array_length(string_to_array($1,'/'),1)-1]
$$;
"""


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def run(args, **kwargs):
    result = subprocess.run([str(a) for a in args], capture_output=True, text=True, **kwargs)
    if result.returncode:
        raise RuntimeError(f"{Path(str(args[0])).name} failed: {result.stderr[-2000:]}")
    return result.stdout


@dataclass
class Database:
    cluster: object = field(repr=False)
    name: str

    def connect(self, user="validation_owner"):
        return psycopg.connect(dbname=self.name, user=user, host=str(self.cluster.socket), autocommit=True)

    @property
    def url(self):
        return f"postgresql+psycopg://validation_owner@/{self.name}?host={quote(str(self.cluster.socket), safe='')}"

    def apply(self, path):
        with self.connect() as conn:
            conn.execute(Path(path).read_text())

    def migrations(self):
        for path in sorted((ROOT / "supabase/migrations").glob("*.sql")):
            self.apply(path)

    def grants(self):
        with self.connect() as conn:
            conn.execute("grant usage on schema public,auth to authenticated")
            conn.execute("grant execute on function auth.uid() to authenticated")
            conn.execute("grant select,insert,update,delete on all tables in schema public to authenticated")
            # Give the role DML privileges, then prove append-only RLS policies block mutations.
            conn.execute("""create or replace function public.validation_identity() returns jsonb
              language sql stable security invoker as $$
              select jsonb_build_object('current_user',current_user,'session_user',session_user,'uid',auth.uid()) $$""")
            conn.execute("revoke all on function public.validation_identity() from public")
            conn.execute("grant execute on function public.validation_identity() to authenticated")

    @contextlib.contextmanager
    def api(self, insights=True):
        server_port = port()
        log = self.cluster.path / f"{self.name}-api-{uuid.uuid4().hex}.log"
        env = {**os.environ, "DATABASE_URL": self.url, "AUTH_DISABLED": "false", "APP_ENV": "production",
               "SUPABASE_JWT_MODE": "hs256", "SUPABASE_JWT_SECRET": self.cluster.secret,
               "SUPABASE_URL": ISSUER, "SUPABASE_SERVICE_ROLE_KEY": "", "OPENAI_API_KEY": "",
               "STT_PROVIDER": "off", "LOCAL_STT_ALLOW_DOWNLOAD": "false",
               "RECORDINGS_DIR": str(self.cluster.path / "recordings"), "PRACTICE_INSIGHTS_ENABLED": str(insights).lower(),
               "PRACTICE_COMPETENCY_EVIDENCE_ENABLED": "false"}
        with log.open("w") as output:
            process = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                                        "--port", str(server_port), "--log-level", "warning"],
                                       cwd=ROOT / "backend", env=env, stdout=output, stderr=subprocess.STDOUT)
            try:
                base = f"http://127.0.0.1:{server_port}"
                for _ in range(200):
                    if process.poll() is not None:
                        raise RuntimeError("Isolated API failed to start: " + self.cluster.clean(log.read_text()[-4000:]))
                    try:
                        if httpx.get(base + "/health", timeout=1).status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.05)
                else:
                    raise RuntimeError("Isolated API startup timeout")
                with httpx.Client(base_url=base, timeout=15) as client:
                    yield client
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()

    @contextlib.contextmanager
    def rest(self):
        self.grants()
        server_port = port()
        env = {**os.environ, "PGRST_DB_URI": f"postgresql://validation_authenticator@/{self.name}?host={quote(str(self.cluster.socket),safe='')}",
               "PGRST_DB_SCHEMAS": "public", "PGRST_DB_ANON_ROLE": "anon", "PGRST_JWT_SECRET": self.cluster.secret,
               "PGRST_JWT_AUD": "authenticated", "PGRST_SERVER_HOST": "127.0.0.1", "PGRST_SERVER_PORT": str(server_port),
               "PGRST_DB_POOL": "2", "PGRST_DB_CHANNEL_ENABLED": "false", "PGRST_LOG_LEVEL": "error"}
        log = self.cluster.path / f"{self.name}-rest.log"
        with log.open("w") as output:
            process = subprocess.Popen([str(POSTGREST)], env=env, stdout=output, stderr=subprocess.STDOUT)
            try:
                base = f"http://127.0.0.1:{server_port}"
                for _ in range(200):
                    if process.poll() is not None:
                        raise RuntimeError("PostgREST failed: " + self.cluster.clean(log.read_text()[-2000:]))
                    try:
                        if httpx.get(base + "/", headers=self.cluster.headers(A), timeout=1).status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.05)
                else:
                    raise RuntimeError("PostgREST startup timeout")
                with httpx.Client(base_url=base, timeout=15) as client:
                    yield client
            finally:
                process.terminate()
                process.wait(timeout=10)


@dataclass
class Cluster:
    path: Path
    secret: str = field(default_factory=lambda: secrets.token_urlsafe(48), repr=False)

    @property
    def socket(self):
        return self.path / "socket"

    def clean(self, value):
        return value.replace(self.secret, "[REDACTED]")

    def headers(self, user=A, *, claims=None, secret=None):
        body = {"sub": user, "iss": ISSUER + "/auth/v1", "aud": "authenticated", "role": "authenticated",
                "exp": int(time.time()) + 600, **(claims or {})}
        return {"Authorization": "Bearer " + jwt.encode(body, secret or self.secret, algorithm="HS256")}

    def database(self, schema="fresh"):
        name = "validation_" + uuid.uuid4().hex[:12]
        with psycopg.connect(dbname="postgres", host=str(self.socket), autocommit=True) as admin:
            admin.execute(sql.SQL("create database {} owner validation_owner").format(sql.Identifier(name)))
        db = Database(self, name)
        with db.connect() as conn:
            conn.execute(BOOTSTRAP)
            conn.execute("insert into auth.users(id) values (%s),(%s)", (A, B))
            if schema == "fresh":
                conn.execute((ROOT / "supabase/schema.sql").read_text())
            elif schema == "historical":
                historical = run(["git", "show", f"{HISTORICAL_SCHEMA_COMMIT}:supabase/schema.sql"], cwd=ROOT)
                conn.execute(historical)
        return db


@pytest.fixture(scope="session")
def cluster():
    RUNTIME.mkdir(parents=True, exist_ok=True)
    runtime_lock = (RUNTIME / ".runtime.lock").open("a")
    fcntl.flock(runtime_lock, fcntl.LOCK_SH)
    if not (PG_BIN / "initdb").exists() or not POSTGREST.exists():
        pytest.fail("Pinned runtime is missing: run scripts/setup_pg_validation_runtime.py first")
    assert "16.15" in run([PG_BIN / "postgres", "--version"])
    assert "16.5" in run([POSTGREST, "--version"])
    path = Path(tempfile.mkdtemp(prefix="jobseeker-pg-run-", dir="/tmp"))
    path.chmod(0o700)
    c = Cluster(path)
    c.socket.mkdir(mode=0o700)
    run([PG_BIN / "initdb", "-D", path / "data", "--auth-local=trust", "--auth-host=reject", "--no-locale", "--encoding=UTF8"])
    with (path / "data/postgresql.conf").open("a") as config:
        config.write(f"\nlisten_addresses=''\nunix_socket_directories='{c.socket}'\nunix_socket_permissions=0700\n"
                     "shared_buffers=32MB\nmax_connections=32\nwork_mem=2MB\nmaintenance_work_mem=16MB\n"
                     "fsync=on\nsynchronous_commit=on\nfull_page_writes=on\n")
    run([PG_BIN / "pg_ctl", "-D", path / "data", "-l", path / "postgres.log", "-w", "start"])
    try:
        with psycopg.connect(dbname="postgres", host=str(c.socket), autocommit=True) as admin:
            admin.execute("create role validation_owner login nosuperuser nobypassrls nocreatedb nocreaterole noinherit")
            admin.execute("create role authenticated nologin nosuperuser nobypassrls nocreatedb nocreaterole noinherit")
            admin.execute("create role anon nologin nosuperuser nobypassrls nocreatedb nocreaterole noinherit")
            admin.execute("create role validation_authenticator login nosuperuser nobypassrls nocreatedb nocreaterole noinherit")
            admin.execute("grant authenticated,anon to validation_authenticator")
        yield c
    finally:
        run([PG_BIN / "pg_ctl", "-D", path / "data", "-w", "stop", "-m", "fast"])
        # No credentials survive the disposable run. Sanitized logs can be retained explicitly.
        if os.environ.get("JOBSEEKER_KEEP_PG_LOGS") == "1":
            logs = ROOT / "backend/integration/results"
            logs.mkdir(exist_ok=True)
            for file in path.glob("*.log"):
                (logs / file.name).write_text(c.clean(file.read_text()))
        shutil.rmtree(path)
        runtime_lock.close()


@pytest.fixture
def database(cluster):
    db = cluster.database()
    db.migrations()
    return db
