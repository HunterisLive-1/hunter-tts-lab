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
import hardware  # noqa: E402
import paths  # noqa: E402
import store  # noqa: E402
from jobs import Job, UserError  # noqa: E402


class InstallOrder(unittest.TestCase):
    def setUp(self):
        paths.ensure()
        store.write(paths.INSTALLED, {})
        self.works = {"cuda13": True, "cuda12": True, "vulkan": True, "cpu": True, "torch-cu128": True, "torch-cu126": True, "torch-cpu": True}
        # seconds for 10 s of voice
        self.speed = {"cuda13": 5.0, "cuda12": 6.0, "vulkan": 8.0, "cpu": 60.0, "torch-cu128": 2.6, "torch-cu126": 3.0, "torch-cpu": 91.0}
        self.fetched: list[str] = []
        self.tested: list[str] = []
        self.downloaded: list[str] = []
        self.error = "it did not start"
        self.dropped: list[tuple] = []

        def fake_runtime(rt, job, start, share):
            self.fetched.append(rt)

        def fake_test(rt, model_id, cancelled=None):
            self.tested.append(rt)
            return {"ok": True, "per10": self.speed[rt]} if self.works[rt] else {"ok": False, "error": self.error}

        patches = [
            mock.patch.object(engines, "fetch", lambda url, *a, **k: self.downloaded.append(url)),
            mock.patch.object(engines, "install_runtime", fake_runtime),
            mock.patch.object(engines, "self_test", fake_test),
            mock.patch.object(engines, "runtime_ready", lambda rt: rt in self.fetched),
            mock.patch.object(engines, "_drop_unused_runtimes", lambda *a, **k: self.dropped.append(k.get("passed_over", a[0] if a else ()))),
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

    def test_only_the_ways_that_were_judged_and_passed_over_are_thrown_away(self):
        self.works["cuda13"] = False  # really does not work here
        self.install("voxcpm2", ["cuda13", "vulkan", "cpu"])
        self.assertEqual(self.dropped[-1], ("cuda13",))
        self.works["cuda13"] = True
        self.error = engines.OUT_OF_VRAM  # the card was merely full during the test
        self.works["vulkan"] = False
        engines.forget_failures()
        store.write(paths.INSTALLED, {})
        self.works["cuda13"] = False
        self.install("voxcpm2", ["cuda13", "vulkan", "cpu"])
        self.assertEqual(self.dropped[-1], ())  # neither is held against the PC, so neither download is deleted

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

    def test_running_out_of_memory_is_not_held_against_a_way_of_running(self):
        self.works["cuda13"] = False
        self.error = engines.OUT_OF_VRAM  # say, a game was open during the test
        r = self.install("voxcpm2", ["cuda13", "vulkan", "cpu"])
        self.assertEqual(r["runtime"], "vulkan")
        self.assertIn("could not be tested just now", r["notes"][0])
        self.assertNotIn("cuda13", engines.installed()["tried"])
        self.works["cuda13"] = True  # the game is closed; "Test again" needs no "Check this PC again" first
        self.tested.clear()
        self.assertEqual(self.install("voxcpm2", ["cuda13", "vulkan", "cpu"])["runtime"], "cuda13")
        self.assertEqual(self.tested, ["cuda13"])

    def test_a_model_that_cannot_be_moved_stays_where_it_was_and_says_so(self):
        # What happened on the first morning: "Processor only" was pressed while another program had the memory.
        self.install("voxcpm2", ["cuda13", "vulkan", "cpu"])
        self.works["cpu"] = False
        self.error = engines.OUT_OF_RAM
        with self.assertRaises(UserError) as caught:
            self.install("voxcpm2", ["cpu"])
        self.assertIn("left as it was", str(caught.exception))
        entry = engines.installed()["models"]["voxcpm2"]
        self.assertEqual(entry["runtime"], "cuda13")
        self.assertIn("still runs on the NVIDIA graphics card", entry["problem"])
        self.assertIn("ran out of memory", entry["problem"])
        self.assertNotIn("cpu", engines.installed()["tried"])
        self.works["cpu"] = True  # the other program is closed
        self.assertEqual(self.install("voxcpm2", ["cpu"])["runtime"], "cpu")
        self.assertNotIn("problem", engines.installed()["models"]["voxcpm2"])

    def test_omnivoice_downloads_all_its_files_and_keeps_the_pytorch_that_works(self):
        r = self.install("omnivoice", ["torch-cu128", "torch-cu126", "torch-cpu"])
        self.assertEqual(r["runtime"], "torch-cu128")
        self.assertEqual(self.tested, ["torch-cu128"])
        self.assertEqual(len(self.downloaded), len(engines.model_files("omnivoice")))
        self.assertTrue(any("whisper" in url for url in self.downloaded))

    def test_omnivoice_moves_on_when_pytorch_cannot_use_the_card(self):
        self.works["torch-cu128"] = False
        r = self.install("omnivoice", ["torch-cu128", "torch-cu126", "torch-cpu"])
        self.assertEqual(r["runtime"], "torch-cu126")
        self.assertIn("did not work here", r["notes"][0])

    def test_omnivoice_on_a_processor_is_simply_accepted(self):
        r = self.install("omnivoice", ["torch-cpu"])
        self.assertEqual((r["runtime"], r["per10"]), ("torch-cpu", 91.0))

    def test_the_two_kinds_of_engine_do_not_share_failures(self):
        self.works["torch-cu128"] = False
        self.install("omnivoice", ["torch-cu128", "torch-cpu"])
        self.tested.clear()
        self.assertEqual(self.install("voxcpm2", ["cuda13", "vulkan", "cpu"])["runtime"], "cuda13")
        self.assertEqual(self.tested, ["cuda13"])


class Engines(unittest.TestCase):
    """Which engine folders are deleted and which are kept, on real folders."""

    def setUp(self):
        import shutil

        paths.ensure()
        shutil.rmtree(paths.RUNTIMES, ignore_errors=True)
        paths.RUNTIMES.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, paths.RUNTIMES, True)

    def engine(self, name, ready=True):
        d = paths.RUNTIMES / name
        d.mkdir(parents=True)
        if name.startswith("torch-"):
            (d / "python").mkdir()
            (d / "python" / "python.exe").write_bytes(b"x")
        else:
            (d / "audiocpp_cli.exe").write_bytes(b"x")
        if ready:
            (d / "READY").write_text("ok", encoding="utf-8")

    def here(self):
        return sorted(d.name for d in paths.RUNTIMES.iterdir())

    def installed(self, **models):
        store.write(paths.INSTALLED, {"models": {m: {"runtime": rt} for m, rt in models.items()}, "tried": {}})

    def test_the_engine_for_the_other_choice_is_kept_when_processor_only_is_switched_on(self):
        for name in ("cuda13", "cpu", "torch-cu128", "torch-cpu"):
            self.engine(name)
        self.installed(voxcpm2="cpu", omnivoice="torch-cpu")  # just moved to the processor
        engines._drop_unused_runtimes()
        self.assertEqual(self.here(), ["cpu", "cuda13", "torch-cpu", "torch-cu128"])  # switching back needs no download
        self.assertEqual(engines.spare_runtimes(), ["cuda13", "torch-cu128"])
        self.assertTrue(4.5 < engines.runtime_disk_gb("torch-cu128") < 5.5)
        engines.drop_spare_runtimes()  # "Free the space"
        self.assertEqual(self.here(), ["cpu", "torch-cpu"])
        self.assertEqual(engines.spare_runtimes(), [])

    def test_an_engine_that_was_tried_and_passed_over_goes_at_once(self):
        for name in ("cuda12", "vulkan"):
            self.engine(name)
        self.installed(chatterbox="vulkan")
        engines._drop_unused_runtimes(passed_over=("cuda12",))
        self.assertEqual(self.here(), ["vulkan"])

    def test_engines_of_a_kind_no_installed_model_uses_go(self):
        for name in ("cuda13", "cpu", "torch-cu128"):
            self.engine(name)
        self.installed(omnivoice="torch-cu128")  # the last audio.cpp model was removed
        engines._drop_unused_runtimes()
        self.assertEqual(self.here(), ["torch-cu128"])

    def test_leftovers_of_a_cut_off_unpacking_go_and_a_half_done_python_stays(self):
        self.engine("cuda13")
        self.engine("cuda12.tmp", ready=False)
        self.engine("torch-cu128", ready=False)  # OmniVoice's Python, cancelled halfway
        self.installed(chatterbox="cuda13")
        engines._drop_unused_runtimes()
        self.assertEqual(self.here(), ["cuda13", "torch-cu128"])
        self.assertEqual(engines.spare_runtimes(), [])  # not counted as something that could be freed
        engines.remove_model("chatterbox")
        self.assertEqual(self.here(), ["torch-cu128"])  # still waiting for its Install

    def test_removing_omnivoice_takes_all_of_its_python_with_it(self):
        self.engine("torch-cu128")
        self.engine("torch-cpu", ready=False)
        self.engine("cuda13")
        self.installed(omnivoice="torch-cu128", chatterbox="cuda13")
        engines.remove_model("omnivoice")
        self.assertEqual(self.here(), ["cuda13"])


class Memory(unittest.TestCase):
    """The engine is not started into memory that is not there."""

    def free(self, gb):
        p = mock.patch.object(hardware, "free_ram_gb", lambda: gb)
        p.start()
        self.addCleanup(p.stop)

    def test_voxcpm2_on_a_processor_with_6_gb_free_is_stopped_with_the_numbers(self):
        self.free(6.0)
        with self.assertRaises(UserError) as caught:
            engines.check_memory("voxcpm2", "cpu")
        self.assertIn("needs about 9.1 GB of free memory on a processor and only 6.0 GB is free right now", str(caught.exception))

    def test_a_little_short_is_let_through(self):
        self.free(8.0)  # Windows can make that much room
        engines.check_memory("voxcpm2", "cpu")

    def test_on_a_graphics_card_the_pc_memory_still_counts_but_less(self):
        self.free(6.0)
        engines.check_memory("voxcpm2", "cuda")  # needs 4.1 GB of RAM there
        self.free(1.0)
        with self.assertRaises(UserError):
            engines.check_memory("chatterbox", "cuda")

    def test_the_engine_dying_for_lack_of_memory_is_said_in_plain_words(self):
        said = "load_backend: loaded CPU backend" + chr(10) + "D:/a/audio.cpp/external/ggml/src/ggml.c:1685: GGML_ASSERT(ctx->mem_buffer != NULL) failed"
        self.assertEqual(engines._explain(3, said), engines.OUT_OF_RAM)
        self.assertEqual(engines._explain(1, "CUDA error: out of memory"), engines.OUT_OF_VRAM)
        self.assertTrue(engines.passing(engines.OUT_OF_RAM) and engines.passing(engines.OUT_OF_VRAM))
        self.assertFalse(engines.passing("Vulkan could not start on this graphics card."))

    def test_the_engines_own_last_word_wins_over_the_rest_of_its_log(self):
        # Found with a Japanese script: the card's ordinary start-up line made this an "NVIDIA could not start".
        log = chr(10).join((
            "ggml_cuda_init: found 1 CUDA devices (Total VRAM: 16283 MiB):",
            "load_backend: loaded CUDA backend from ggml-cuda.dll",
            "audiocpp_cli failed: unsupported Chatterbox language: ja",
        ))
        self.assertIn("cannot speak that language", engines._explain(1, log))
        self.assertNotIn("NVIDIA", engines._explain(1, log))
        # a real failure of the card is still called that
        self.assertIn("NVIDIA", engines._explain(1, "audiocpp_cli failed: CUDA initialization failed"))
        self.assertIn("NVIDIA", engines._explain(1, "no CUDA devices found"))
        # memory, said on a line above the last word, is still found
        full = "ggml_cuda_init: found 1 CUDA devices" + chr(10) + "CUDA error: out of memory" + chr(10) + "audiocpp_cli failed: failed to run graph"
        self.assertEqual(engines._explain(1, full), engines.OUT_OF_VRAM)
        # and anything else is passed on in the engine's own words
        self.assertEqual(engines._explain(1, "audiocpp_cli failed: something new and odd"), "something new and odd")


if __name__ == "__main__":
    unittest.main()
