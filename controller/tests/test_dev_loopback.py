"""DEV ONLY (branch dev/tools): loopback through the ingress-only gate.

The dev add-on admits 127.0.0.1 and ::1 so the controller's own tools work
from inside its container. These pin that the flag is the only way in, that
it opens loopback and nothing else, and that it never makes loopback a
trusted source of Supervisor's identity headers.
"""
import subprocess
from pathlib import Path

import em_ingressauth as ia

GATEWAY = ia.INGRESS_GATEWAY_IP
ROOT = Path(__file__).resolve().parent.parent


def admits(remote, ingress_only=True, dev_loopback=False):
    return ia.admits_peer(remote, ingress_only=ingress_only, dev_loopback=dev_loopback)


def test_without_the_flag_loopback_is_refused_as_before():
    assert admits(GATEWAY)
    assert not admits("127.0.0.1")
    assert not admits("::1")


def test_the_flag_opens_loopback_and_nothing_else():
    for peer in ("127.0.0.1", "::1"):
        assert admits(peer, dev_loopback=True)
    for peer in ("192.168.1.2", "127.0.0.2", "172.30.32.3", "", None, "::ffff:127.0.0.1"):
        assert not admits(peer, dev_loopback=True), peer


def test_outside_the_add_on_every_peer_is_admitted_as_before():
    assert admits("192.168.1.2", ingress_only=False)


def test_loopback_is_never_a_source_of_identity():
    # Supervisor's headers count only from the gateway, flag or not.
    assert ia.decide(ingress_only=True, remote="127.0.0.1",
                     user_id="abc", username="x", display_name="x") is None


def test_only_the_dev_add_on_carries_the_flag(tmp_path):
    assert "EM_DEV_ADMIT_LOOPBACK" not in (ROOT / "config.yaml").read_text()
    out = tmp_path / "dev"
    subprocess.run(["sh", str(ROOT / "tools/make_dev_addon.sh"), str(out)],
                   check=True, capture_output=True)
    assert 'EM_DEV_ADMIT_LOOPBACK: "1"' in (out / "config.yaml").read_text()


def test_through_the_real_middleware(tmp_path, monkeypatch):
    """aiohttp's test client connects from 127.0.0.1: refused by the add-on's
    gate without the flag (the released add-on), let through with it."""
    import asyncio
    from aiohttp.test_utils import TestClient, TestServer
    import em_api
    import em_db as db

    db.init(str(tmp_path / "t.db"))
    monkeypatch.setattr(ia, "INGRESS_ONLY", True)

    async def status(flag):
        monkeypatch.setattr(ia, "DEV_ADMIT_LOOPBACK", flag)
        app = await em_api.create_app()
        async with TestClient(TestServer(app, host="127.0.0.1")) as client:
            return (await client.get("/api/system/setup-state")).status

    try:
        assert asyncio.run(status(False)) == 403
        assert asyncio.run(status(True)) == 200
    finally:
        if db._conn is not None:
            db._conn.close()
            db._conn = None
