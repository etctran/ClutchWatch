import base64
import importlib
import json
from unittest import mock

import fakeredis
import pytest
from fastapi.testclient import TestClient

from ingest.replayer import load_games


@pytest.fixture()
def proc():
    with mock.patch("redis.Redis", lambda **k: fakeredis.FakeRedis(decode_responses=True)), \
         mock.patch("google.cloud.pubsub_v1.PublisherClient"):
        import processor.app as p
        importlib.reload(p)
        yield p


def events():
    return [e.to_dict() | {"published_at": "2026-01-01T00:00:00+00:00"}
            for _, e in load_games("tests/fixtures/hist_22400001.csv")[0]]


def rows(p):
    return [json.loads(c.args[1]) for c in p.publisher.publish.call_args_list]


def test_process_full_game_then_redelivery(proc):
    evs = events()
    assert all(proc.process(e) for e in evs)
    assert all(proc.process(e) for e in evs)  # duplicates are acked, not re-applied
    st = proc.state.get("0022400001")
    assert (st["applied"], st["home_score"], st["away_score"]) == ("538", "116", "117")
    out = rows(proc)
    state_rows = [r for r in out if "processed_at" in r]
    assert len(state_rows) == 2 * 538 and sum(r["duplicate"] for r in state_rows) == 538
    assert any("alert_id" in r for r in out)  # the 1-point game fires CLOSE_LATE


def test_force_nack_only_after_apply(proc):
    proc.FORCE_NACK_RATE = 1.0
    e = events()[0]
    assert proc.process(e) is False       # applied, then NACKed on purpose
    assert proc.process(e) is True        # redelivery: duplicate, acked
    assert proc.state.get("0022400001")["applied"] == "1"


def test_pull_callback_acks_and_nacks(proc):
    e = events()[0]
    ok = mock.Mock(data=json.dumps(e).encode())
    proc._on_message(ok)
    ok.ack.assert_called_once()
    bad = mock.Mock(data=b"not json", message_id="m1")
    proc._on_message(bad)  # exception -> nack, subscriber keeps running
    bad.nack.assert_called_once()


def test_push_endpoint_maps_to_status(proc):
    c = TestClient(proc.app)
    body = {"message": {"data": base64.b64encode(json.dumps(events()[0]).encode()).decode()}}
    assert c.post("/", json=body).status_code == 204
    proc.FORCE_NACK_RATE = 1.0
    body = {"message": {"data": base64.b64encode(json.dumps(events()[1]).encode()).decode()}}
    assert c.post("/", json=body).status_code == 500
