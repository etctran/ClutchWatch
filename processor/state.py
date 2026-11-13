"""Per-game state in Redis, applied idempotently.

One Lua script does the duplicate check (SET NX on event_id) and the state update
atomically, so a crash can never leave "marked seen but not applied" or the reverse.
"""
import json

import redis

TTL_SECONDS = 7 * 24 * 3600

# KEYS[1] = seen:<event_id>   KEYS[2] = game:<game_id>
# ARGV    = order_number, home_score, away_score, period, clock_seconds, home, away, ttl
# Returns 0 if a duplicate, 1 if applied but older than current state (late-entered play),
# 2 if applied and it advanced the state.
_APPLY = """
if not redis.call('SET', KEYS[1], 1, 'NX', 'EX', ARGV[8]) then return 0 end
redis.call('HINCRBY', KEYS[2], 'applied', 1)
local last = tonumber(redis.call('HGET', KEYS[2], 'order_number') or '-1')
if tonumber(ARGV[1]) > last then
  redis.call('HSET', KEYS[2], 'order_number', ARGV[1], 'home_score', ARGV[2],
             'away_score', ARGV[3], 'period', ARGV[4], 'clock_seconds', ARGV[5],
             'home_team', ARGV[6], 'away_team', ARGV[7])
  redis.call('EXPIRE', KEYS[2], ARGV[8])
  return 2
end
redis.call('EXPIRE', KEYS[2], ARGV[8])
return 1
"""


class GameState:
    def __init__(self, r: redis.Redis):
        self.r = r
        self._apply = r.register_script(_APPLY)

    def apply(self, ev: dict) -> int:
        """0 = duplicate (redelivery), 1 = applied but late (older order_number), 2 = advanced state."""
        return int(self._apply(
            keys=[f"seen:{ev['event_id']}", f"game:{ev['game_id']}"],
            args=[ev["order_number"], ev["home_score"], ev["away_score"], ev["period"],
                  ev["clock_seconds"], ev["home_team"], ev["away_team"], TTL_SECONDS],
        ))

    def get(self, game_id: str) -> dict:
        return self.r.hgetall(f"game:{game_id}")

    def alert_state(self, game_id: str) -> dict | None:
        raw = self.r.get(f"alerts:{game_id}")
        return json.loads(raw) if raw else None

    def save_alert_state(self, game_id: str, st: dict) -> None:
        self.r.set(f"alerts:{game_id}", json.dumps(st), ex=TTL_SECONDS)
