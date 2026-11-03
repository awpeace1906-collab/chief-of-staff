import pytest
from fastapi.testclient import TestClient

from cos import agent, db, push, voice
from cos.main import create_app

TOKEN = "ab" * 32


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "cos.db")
    yield c
    c.close()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("COS_API_TOKEN", raising=False)
    for v in push.ENV_VARS + ("APNS_ENV",):
        monkeypatch.delenv(v, raising=False)
    with TestClient(create_app(str(tmp_path / "cos.db"))) as c:
        yield c


@pytest.fixture
def apns_env(monkeypatch):
    for v in push.ENV_VARS:
        monkeypatch.setenv(v, "x")
    monkeypatch.setattr(push, "_provider_token", lambda: "jwt")


class FakeResponse:
    def __init__(self, status, reason=""):
        self.status_code, self.reason = status, reason

    def json(self):
        return {"reason": self.reason} if self.reason else {}


class FakeClient:
    def __init__(self, replies):
        self.replies, self.calls = replies, []

    def post(self, url, headers, json):
        self.calls.append((url, headers, json))
        return FakeResponse(*self.replies[url.rsplit("/", 1)[1]])

    def close(self):
        pass


def test_register_rejects_bad_tokens(client):
    for bad in ("", "xyz", "ab" * 10, "zz" * 32, 123):
        assert client.post("/api/push/register", json={"token": bad}).status_code == 422
    assert client.post("/api/push/register", json={}).status_code == 422


def test_register_and_status(client):
    assert client.get("/api/push/status").json() == {"configured": False, "tokens": 0}
    assert client.post("/api/push/register", json={"token": TOKEN}).json() == {"ok": True, "tokens": 1}
    assert client.post("/api/push/register", json={"token": TOKEN.upper()}).json()["tokens"] == 1  # same device
    assert client.get("/api/push/status").json() == {"configured": False, "tokens": 1}


def test_tokens_are_not_exported(client):
    client.post("/api/push/register", json={"token": TOKEN})
    assert TOKEN not in client.get("/api/export").text
    assert TOKEN not in client.get("/api/settings").text


def test_status_configured(client, apns_env):
    assert client.get("/api/push/status").json()["configured"] is True


def test_notify_all_drops_dead_tokens(conn, apns_env, monkeypatch):
    monkeypatch.setenv("APNS_ENV", "sandbox")
    good, gone, bad, busy = "a" * 64, "b" * 64, "c" * 64, "d" * 64
    for t in (good, gone, bad, busy):
        push.register(conn, t)
    fake = FakeClient({good: (200,), gone: (410, "Unregistered"), bad: (400, "BadDeviceToken"), busy: (429, "TooManyRequests")})
    out = push.notify_all(conn, client=fake)
    assert out == {"sent": 1, "dropped": 2, "failed": 1}
    assert push.tokens(conn) == [good, busy]
    url, headers, body = fake.calls[0]
    assert url == f"https://api.sandbox.push.apple.com/3/device/{good}"
    assert headers["apns-push-type"] == "background" and headers["apns-priority"] == "5"
    assert headers["apns-topic"] == "x" and headers["authorization"] == "bearer jwt"
    assert body == {"aps": {"content-available": 1}}


def test_notify_all_noop_when_unconfigured(conn, monkeypatch):
    for v in push.ENV_VARS:
        monkeypatch.delenv(v, raising=False)
    push.register(conn, TOKEN)
    assert push.notify_all(conn, client=FakeClient({})) == {"sent": 0, "dropped": 0}


def test_production_host(monkeypatch):
    monkeypatch.delenv("APNS_ENV", raising=False)
    assert push.host() == "api.push.apple.com"


def test_check_survives_push_failure(conn, apns_env, monkeypatch):
    push.register(conn, TOKEN)

    def boom(_conn):
        raise RuntimeError("apns down")

    monkeypatch.setattr(push, "notify_all", boom)
    report = agent.check(conn, google=None, capture_mail=False)
    assert "push" not in report
    assert conn.execute("SELECT 1 FROM audit_log WHERE action = 'push.failed'").fetchone()


def test_voice_transcribe(client, monkeypatch):
    seen = {}

    def fake(data, suffix):
        seen.update(data=data, suffix=suffix)
        return "call the dentist"

    monkeypatch.setattr(voice, "transcribe", fake)
    r = client.post("/api/voice/transcribe", files={"audio": ("voice.m4a", b"\x00\x01", "audio/mp4")})
    assert r.status_code == 200 and r.json() == {"text": "call the dentist"}
    assert seen == {"data": b"\x00\x01", "suffix": ".m4a"}


def test_voice_unavailable(client, monkeypatch):
    def missing(data, suffix):
        raise voice.VoiceUnavailable("voice transcription needs faster-whisper")

    monkeypatch.setattr(voice, "transcribe", missing)
    r = client.post("/api/voice/transcribe", files={"audio": ("voice.m4a", b"\x00", "audio/mp4")})
    assert r.status_code == 501 and "faster-whisper" in r.json()["detail"]


def test_voice_empty(client):
    assert client.post("/api/voice/transcribe", files={"audio": ("v.m4a", b"", "audio/mp4")}).status_code == 422
