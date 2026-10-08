"""How install picks a way of running the engine, with the downloads and the
engine itself replaced by stand-ins.

    python -m unittest discover tests
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
os.environ.setdefault("HUNTER_TTS_LAB_DATA", tempfile.mkdtemp(prefix="htl-test-"))

import engines  # noqa: E402
import paths  # noqa: E402
import store  # noqa: E402
from jobs import Job, UserError  # noqa: E402


class InstallOrder(unittest.TestCase):
    def setUp(self):
        paths.ensure()
        store.write(paths.INSTALLED, {})
        self.works = {"cuda13": True, "cuda12": True, "vulkan": True, "cpu": True}
        self.speed = {"cuda13": 5.0, "cuda12": 6.0, "vulkan": 8.0, "cpu": 60.0}  # seconds for 10 s of voice
        self.fetched: list[str] = []
        self.tested: list[str] = []

        def fake_runtime(rt, job, start, share):
            self.fetched.append(rt)

        def fake_test(rt, model_id, cancelled=None):
            self.tested.append(rt)
            return {"ok": True, "per10": self.speed[rt]} if self.works[rt] else {"ok": False, "error": "it did not start"}

        patches = [
            mock.patch.object(engines, "fetch", lambda *a, **k: None),
            mock.patch.object(engines, "install_runtime", fake_runtime),
            mock.patch.object(engines, "self_test", fake_test),
            mock.patch.object(engines, "runtime_ready", lambda rt: rt in self.fetched),
            mock.patch.object(engines, "_drop_unused_runtimes", lambda: None),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def install(self, model, order):
        return engines.install_model(Job("install", "test"), model, order)

    def test_the_first_way_that_speaks_is_kept(self):
        r = self.install("voxcpm2", ["cuda13", "vulkan", "cpu"])
        self.assertEqual(r["runtime"], "cuda13")
        self.assertEqual(self.tested, ["cuda13"])
        self.assertEqual(r["notes"], [])

    def test_a_way_that_fails_its_test_is_passed_over_and_said_so(self):
        self.works["cuda13"] = False
        r = self.install("voxcpm2", ["cuda13", "vulkan", "cpu"])
        self.assertEqual(r["runtime"], "vulkan")
        self.assertEqual(self.tested, ["cuda13", "vulkan"])
        self.assertIn("did not work here", r["notes"][0])
        self.assertIs(engines.installed()["tried"]["cuda13"]["ok"], False)

    def test_a_known_failure_is_not_downloaded_again_for_the_next_model(self):
        self.works["cuda13"] = False
        self.install("voxcpm2", ["cuda13", "vulkan", "cpu"])
        self.fetched.clear()
        self.tested.clear()
        r = self.install("chatterbox", ["cuda13", "vulkan", "cpu"])
        self.assertEqual(r["runtime"], "vulkan")
        self.assertNotIn("cuda13", self.fetched)
        self.assertEqual(self.tested, ["vulkan"])

    def test_checking_the_pc_again_gives_a_failed_way_another_chance(self):
        self.works["cuda13"] = False
        self.install("voxcpm2", ["cuda13", "vulkan", "cpu"])
        self.works["cuda13"] = True  # say, after a driver update
        engines.forget_failures()
        self.assertEqual(self.install("voxcpm2", ["cuda13", "vulkan", "cpu"])["runtime"], "cuda13")

    def test_going_back_from_processor_to_graphics_card_really_goes_back(self):
        self.install("voxcpm2", ["cpu"])
        self.assertEqual(engines.installed()["models"]["voxcpm2"]["runtime"], "cpu")
        r = self.install("voxcpm2", ["cuda13", "vulkan", "cpu"])
        self.assertEqual(r["runtime"], "cuda13")  # not "cpu", although cpu is installed and works

    def test_a_graphics_way_that_is_secretly_slow_is_not_settled_for(self):
        # What the older NVIDIA build did on a 50-series card: it "worked", at processor speed.
        self.speed["cuda12"] = 66.0
        r = self.install("chatterbox", ["cuda12", "vulkan", "cpu"])
        self.assertEqual(self.tested, ["cuda12", "vulkan"])
        self.assertEqual(r["runtime"], "vulkan")
        self.assertEqual(r["per10"], 8.0)
        self.assertIn("slowly", r["notes"][0])

    def test_when_every_way_is_slow_the_fastest_is_kept(self):
        self.speed.update(cuda13=70.0, vulkan=40.0, cpu=55.0)  # a very weak card
        r = self.install("chatterbox", ["cuda13", "vulkan", "cpu"])
        self.assertEqual(self.tested, ["cuda13", "vulkan", "cpu"])
        self.assertEqual(r["runtime"], "vulkan")

    def test_a_slow_processor_is_simply_accepted(self):
        self.speed["cpu"] = 300.0
        self.assertEqual(self.install("chatterbox", ["cpu"])["runtime"], "cpu")

    def test_nothing_works_is_an_error_that_names_what_was_tried(self):
        self.works.update(cuda13=False, vulkan=False, cpu=False)
        with self.assertRaises(UserError) as caught:
            self.install("chatterbox", ["cuda13", "vulkan", "cpu"])
        self.assertEqual(self.tested, ["cuda13", "vulkan", "cpu"])
        self.assertIn("Processor only", str(caught.exception))
        self.assertNotIn("chatterbox", engines.installed()["models"])


if __name__ == "__main__":
    unittest.main()
