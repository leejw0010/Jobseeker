"""Real locally served JWKS, never a Supabase/cloud request."""
import json
import threading
import time
import uuid
from types import SimpleNamespace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from app.config import settings


@pytest.fixture
def jwks_server(monkeypatch):
    state = {"keys": [], "status": 200, "requests": []}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            state["requests"].append(self.path)
            self.send_response(state["status"])
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"keys": state["keys"]}).encode())

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    issuer = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setattr(settings, "auth_disabled", False)
    monkeypatch.setattr(settings, "jwt_mode", "jwks", raising=False)
    monkeypatch.setattr(settings, "supabase_url", issuer)
    monkeypatch.setattr(settings, "jwt_secret", "")
    try:
        yield state, issuer
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def signed(issuer, key, kid="first", algorithm="RS256", **claims):
    body = {"sub": str(uuid.uuid4()), "aud": "authenticated", "iss": issuer + "/auth/v1",
            "exp": int(time.time()) + 300, **claims}
    return jwt.encode(body, key, algorithm=algorithm, headers={"kid": kid, "jku": "http://untrusted.invalid/keys"})


def keypair(kid="first", algorithm="RS256"):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048) if algorithm == "RS256" else ec.generate_private_key(ec.SECP256R1())
    jwk = json.loads(jwt.algorithms.get_default_algorithms()[algorithm].to_jwk(key.public_key()))
    return key, {**jwk, "kid": kid, "alg": algorithm, "use": "sig"}


def get(client, token):
    return client.get("/track/applications", headers={"Authorization": "Bearer " + token})


@pytest.mark.parametrize("algorithm", ["RS256", "ES256"])
def test_jwks_accepts_pinned_issuer_and_ignores_token_jku(client, jwks_server, algorithm):
    state, issuer = jwks_server
    key, jwk = keypair(algorithm=algorithm)
    state["keys"] = [jwk]
    assert get(client, signed(issuer, key, algorithm=algorithm)).status_code == 200
    assert state["requests"] == ["/auth/v1/.well-known/jwks.json"]


def test_jwks_refreshes_on_new_kid_and_rejects_unknown_key(client, jwks_server, monkeypatch):
    state, issuer = jwks_server
    key, jwk = keypair()
    state["keys"] = [jwk]
    assert get(client, signed(issuer, key)).status_code == 200
    rotated, rotated_jwk = keypair("rotated")
    state["keys"] = [rotated_jwk]
    # PyJWT rate-limits unknown-kid refetches; advance its clock past that cooldown.
    clock = time.monotonic()
    monkeypatch.setattr(jwt.jwks_client, "time", SimpleNamespace(monotonic=lambda: clock + 31), raising=False)
    assert get(client, signed(issuer, rotated, kid="rotated")).status_code == 200
    assert len(state["requests"]) == 2
    assert get(client, signed(issuer, key, kid="unknown")).status_code == 401


@pytest.mark.parametrize("change", [{"iss": "https://attacker.invalid/auth/v1"}, {"aud": "anon"},
                                  {"exp": int(time.time()) - 30}, {"sub": "bad"}])
def test_jwks_rejects_wrong_claims(client, jwks_server, change):
    state, issuer = jwks_server
    key, jwk = keypair()
    state["keys"] = [jwk]
    assert get(client, signed(issuer, key, **change)).status_code == 401


def test_jwks_fetch_failure_is_401_without_internal_details(client, jwks_server):
    state, issuer = jwks_server
    key, _ = keypair()
    state["status"] = 503
    response = get(client, signed(issuer, key))
    assert response.status_code == 401
    assert issuer not in response.text


def test_jwks_mode_rejects_hs256_even_with_a_configured_secret(client, jwks_server, monkeypatch):
    _, issuer = jwks_server
    secret = "local-test-only-key-that-is-at-least-32-bytes"
    monkeypatch.setattr(settings, "jwt_secret", secret)
    assert get(client, signed(issuer, secret, algorithm="HS256")).status_code == 401
