"""Unit tests for the healer's decision logic - no Docker needed.

Run:  python test_self_healer.py
A fake Docker + fake clock simulate outages deterministically.
"""
import unittest

import config
import self_healer as sh

config.FAILURE_THRESHOLD = 3
config.RECOVERY_TIMEOUT_S = 30
config.BACKOFF_BASE_S = 5
config.MAX_RESTART_ATTEMPTS = 3
config.STABLE_AFTER_S = 30

SPECS = [
    {"name": "postgres", "container": "pg", "health_url": None, "depends_on": []},
    {"name": "auth", "container": "au", "health_url": "http://auth", "depends_on": []},
    {"name": "inventory", "container": "inv", "health_url": "http://inv", "depends_on": ["postgres", "auth"]},
]


class FakeWorld:
    """Simulated containers: status + whether the app answers /health."""
    def __init__(self):
        self.t = 1000.0
        self.status = {"pg": "running", "au": "running", "inv": "running"}
        self.serving = {"pg": True, "au": True, "inv": True}
        self.heals_work = True          # does a restart actually fix things?
        self.commands = []

    # docker interface
    def state(self, c):
        return {"status": self.status[c], "health": None}

    def start(self, c):
        self.commands.append(("start", c))
        if self.heals_work:
            self.status[c] = "running"; self.serving[c] = True
        return True, "ok"

    def restart(self, c):
        self.commands.append(("restart", c))
        if self.heals_work:
            self.status[c] = "running"; self.serving[c] = True
        return True, "ok"

    # probe
    def probe(self, url, timeout):
        c = {"http://auth": "au", "http://inv": "inv"}[url]
        ok = self.status[c] == "running" and self.serving[c]
        return ok, None if ok else "ConnectionError"

    def kill(self, c):
        self.status[c] = "exited"; self.serving[c] = False

    def hang(self, c):
        self.serving[c] = False         # still "running" but not answering


def make():
    w = FakeWorld()
    h = sh.SelfHealer(SPECS, docker=w, probe=w.probe, clock=lambda: w.t, run_actions_async=False)
    return w, h


def run(w, h, seconds, step=2):
    for _ in range(int(seconds / step)):
        w.t += step
        h.tick()


def events(h):
    return [e["event"] for e in h.events]


class Tests(unittest.TestCase):
    def test_steady_state_does_nothing(self):
        w, h = make(); run(w, h, 20)
        self.assertEqual(w.commands, [])
        self.assertEqual(h.snapshot()["overall"], "HEALTHY")

    def test_blip_is_ignored(self):
        w, h = make(); run(w, h, 4)
        w.hang("au"); run(w, h, 2)          # one failed check
        w.serving["au"] = True; run(w, h, 4)
        self.assertEqual(w.commands, [])
        self.assertIn("BLIP_CLEARED", events(h))

    def test_stopped_container_is_started(self):
        w, h = make(); run(w, h, 4)
        w.kill("au"); run(w, h, 12)
        self.assertEqual(w.commands, [("start", "au")])
        rec = h.records["auth"]
        self.assertEqual(rec.state, sh.HEALTHY)
        self.assertEqual(rec.total_recoveries, 1)
        self.assertIsNotNone(rec.last_recovery_s)

    def test_hung_container_is_restarted(self):
        w, h = make(); run(w, h, 4)
        w.hang("inv"); run(w, h, 12)
        self.assertEqual(w.commands, [("restart", "inv")])
        self.assertEqual(h.records["inventory"].state, sh.HEALTHY)

    def test_dependency_fixed_first(self):
        w, h = make(); run(w, h, 4)
        w.kill("pg"); w.hang("inv")                 # db down AND inventory failing
        run(w, h, 20)
        self.assertEqual(w.commands[0], ("start", "pg"))   # postgres first
        self.assertEqual(h.snapshot()["overall"], "HEALTHY")
        self.assertIn("WAITING_ON_DEPENDENCY", events(h))

    def test_gives_up_after_max_attempts(self):
        w, h = make(); run(w, h, 4)
        w.heals_work = False
        w.kill("au"); run(w, h, 300)
        self.assertEqual(h.records["auth"].state, sh.GAVE_UP)
        self.assertEqual(len(w.commands), config.MAX_RESTART_ATTEMPTS)
        self.assertIn("GAVE_UP", events(h))
        n = len(w.commands); run(w, h, 100)
        self.assertEqual(len(w.commands), n)        # no endless restart loop

    def test_retry_then_success(self):
        w, h = make(); run(w, h, 4)
        w.heals_work = False
        w.kill("au"); run(w, h, 50)                 # first attempt fails
        w.heals_work = True; run(w, h, 60)          # a later retry works
        self.assertEqual(h.records["auth"].state, sh.HEALTHY)
        self.assertGreaterEqual(len(w.commands), 2)

    def test_manual_heal_overrides_breaker(self):
        w, h = make(); run(w, h, 4)
        w.heals_work = False
        w.kill("au"); run(w, h, 300)
        self.assertEqual(h.records["auth"].state, sh.GAVE_UP)
        w.heals_work = True
        self.assertTrue(h.manual_heal("auth")["ok"])
        run(w, h, 6)
        self.assertEqual(h.records["auth"].state, sh.HEALTHY)

    def test_paused_healer_does_not_act(self):
        w, h = make(); run(w, h, 4)
        h.pause(True); w.kill("au"); run(w, h, 30)
        self.assertEqual(w.commands, [])
        h.pause(False); run(w, h, 12)
        self.assertEqual(w.commands, [("start", "au")])

    def test_snapshot_shape(self):
        w, h = make(); run(w, h, 4)
        snap = h.snapshot()
        self.assertEqual({s["service"] for s in snap["services"]}, {"postgres", "auth", "inventory"})
        self.assertIn("policy", snap)


if __name__ == "__main__":
    unittest.main(verbosity=2)
