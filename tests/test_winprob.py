import pytest

from processor.winprob import WinProb, features, seconds_left


def test_seconds_left():
    assert seconds_left(1, 720) == 2880
    assert seconds_left(4, 90) == 90
    assert seconds_left(5, 300) == 300  # OT is its own short period


def test_features():
    assert features(4, 4, 99) == [4, 99 / 60, 4 / 10]


@pytest.fixture(scope="module")
def wp() -> WinProb:
    return WinProb()


def test_wp_behaves(wp):
    tip = wp.home(0, 0, 1, 720)
    assert 0.5 < tip < 0.6  # small home-court edge at tip-off
    assert wp.home(10, 0, 4, 30) > 0.99
    assert wp.home(0, 10, 4, 30) < 0.01
    # same lead is worth more with less time left
    assert wp.home(5, 0, 1, 720) < wp.home(5, 0, 4, 300) < wp.home(5, 0, 4, 30)
    # monotonic in margin
    ps = [wp.home(m, 0, 3, 400) for m in range(-15, 16)]
    assert ps == sorted(ps)
