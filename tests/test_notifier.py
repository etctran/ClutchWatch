import base64
import json
from unittest import mock

import fakeredis
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def notifier():
    with mock.patch("redis.Redis", lambda **k: fakeredis.FakeRedis(decode_responses=True)), \
         mock.patch("google.cloud.pubsub_v1.PublisherClient"):
        import importlib

        import notifier.app as n
        importlib.reload(n)
        with mock.patch.object(n, "requests") as req:
            req.RequestException = Exception
            yield n, req, TestClient(n.app)


def push(client, alert_id="g:CLOSE_LATE:4"):
    a = {"alert_id": alert_id, "game_id": "g", "rule": "CLOSE_LATE", "text": "hi",
         "published_at": "2026-01-01T00:00:00+00:00", "alerted_at": "2026-01-01T00:00:00.1+00:00"}
    return client.post("/", json={"message": {"data": base64.b64encode(json.dumps(a).encode()).decode()}})


def test_redelivered_alert_posts_once(notifier):
    n, req, c = notifier
    req.post.return_value.status_code = 204
    assert push(c).status_code == 204
    assert push(c).status_code == 204  # Pub/Sub redelivery
    assert push(c).status_code == 204  # processor re-fired same alert_id
    assert req.post.call_count == 1
    assert n.publisher.publish.call_count == 1
    assert json.loads(n.publisher.publish.call_args.args[1])["discord_status"] == 204


def test_rate_limited_then_retry(notifier):
    n, req, c = notifier
    req.post.return_value.status_code = 429
    assert push(c).status_code == 503  # Pub/Sub will back off and redeliver
    req.post.return_value.status_code = 204
    assert push(c).status_code == 204
    assert req.post.call_count == 2 and n.publisher.publish.call_count == 1
