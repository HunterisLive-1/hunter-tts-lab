"""OmniVoice's helper process: starting it, talking to it, and what happens
when it fails. PyTorch is replaced by tests/fake_omni_worker.py, which speaks
the same lines.

    python -m unittest discover tests
"""

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
os.environ.setdefault("HUNTER_TTS_LAB_DATA", tempfile.mkdtemp(prefix="htl-test-"))

import engines  # noqa: E402
import hardware  # noqa: E402
import omni_engine  # noqa: E402
import paths  # noqa: E402
import store  # noqa: E402
from downloads import Cancelled  # noqa: E402
from jobs import UserError  # noqa: E402

FAKE = Path(__file__).with_name("fake_omni_worker.py")
VOICE = paths.WEB / "sample-voice.wav"


class Helper(unittest.TestCase):
    def setUp(self):
        paths.ensure()
        store.write(paths.HEARD, {})
        self.box = Path(tempfile.mkdtemp(prefix="htl-fake-"))
        os.environ["FAKE_OMNI_DIR"] = str(self.box)
        self.mode("ok")
        self.out = paths.DOWNLOADS / "test-omni.wav"
        self.free = 64.0  # GB of memory free, as the app will be told
        for p in (mock.patch.object(omni_engine, "python_exe", lambda rt: Path(sys.executable)), mock.patch.object(omni_engine, "WORKER", FAKE),
                  mock.patch.object(hardware, "free_ram_gb", lambda: self.free)):  # fmt: skip
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(omni_engine.stop)

    def mode(self, how: str) -> None:
        (self.box / "mode.txt").write_text(how, encoding="utf-8")

    def ops(self) -> list[str]:
        try:
            return (self.box / "ops.txt").read_text(encoding="utf-8").split()
        except OSError:
            return []

    def speak(self, rt="torch-cu128", text="Namaste doston.", **more):
        return omni_engine.speak(rt, text, self.out, VOICE, "hi", **more)

    def test_a_clip_is_made_and_the_voice_is_listened_to_only_once(self):
        r = self.speak()
        self.assertEqual((r["audio"], r["work"]), (2.0, 0.5))
        self.assertTrue(self.out.exists())
        self.speak()
        self.speak()
        self.assertEqual(self.ops(), ["hear", "speak", "speak", "speak"])
        self.assertEqual(list(store.read(paths.HEARD, {}).values()), ["what the recording says"])  # tidied, and kept on disk

    def test_what_was_heard_is_still_known_after_a_restart(self):
        self.speak()
        omni_engine.stop()
        self.assertFalse(omni_engine.running())
        self.speak()
        self.assertEqual(self.ops(), ["hear", "speak", "speak"])

    def test_the_request_carries_the_words_and_the_steps_for_the_device(self):
        self.speak("torch-cu128", "Hindi: " + chr(0x0928) + chr(0x092E) + chr(0x0938) + chr(0x094D) + chr(0x0924) + chr(0x0947))
        sent = json.loads((self.box / "last_request.json").read_text(encoding="utf-8"))
        self.assertEqual(sent["steps"], 32)
        self.assertEqual(sent["voice_text"], "what the recording says")
        self.assertTrue(sent["text"].endswith(chr(0x0947)))  # Hindi letters arrive whole
        self.speak("torch-cpu")
        sent = json.loads((self.box / "last_request.json").read_text(encoding="utf-8"))
        self.assertEqual(sent["steps"], 16)  # and a different device means a different helper

    def test_status_says_what_the_wait_is_for_and_then_clears(self):
        said: list[str] = []
        self.speak(status=said.append)
        self.assertIn("Listening", said[0])
        self.assertEqual(said[-1], "")
        said.clear()
        self.speak(status=said.append)
        self.assertEqual(said, [""])  # nothing to wait for the second time

    def test_no_nvidia_card_for_pytorch_is_said_in_plain_words(self):
        self.mode("no_cuda")
        with self.assertRaises(UserError) as caught:
            self.speak()
        self.assertIn("driver", str(caught.exception))
        self.assertFalse(omni_engine.running())
        test = omni_engine.self_test("torch-cu128")
        self.assertFalse(test["ok"])
        self.assertIn("driver", test["error"])

    def test_a_helper_that_cannot_even_start_is_an_error_not_a_hang(self):
        self.mode("dead_on_arrival")
        t0 = time.time()
        with self.assertRaises(UserError) as caught:
            self.speak()
        self.assertLess(time.time() - t0, 20)
        self.assertIn("stopped unexpectedly", str(caught.exception))

    def test_a_crash_in_the_middle_is_reported_and_the_next_clip_starts_afresh(self):
        self.speak()
        self.mode("die")
        with self.assertRaises(UserError) as caught:
            self.speak()
        self.assertIn("something broke inside", str(caught.exception))
        self.mode("ok")
        self.assertEqual(self.speak()["audio"], 2.0)

    def test_running_out_of_memory_names_the_right_memory(self):
        self.mode("memory")
        with self.assertRaises(UserError) as caught:
            self.speak("torch-cu128")
        self.assertIn("graphics card ran out of memory", str(caught.exception))
        with self.assertRaises(UserError) as caught:
            self.speak("torch-cpu")
        self.assertIn("PC ran out of memory", str(caught.exception))

    def test_it_is_not_even_started_when_the_memory_is_not_there(self):
        self.free = 2.1
        with self.assertRaises(UserError) as caught:
            self.speak("torch-cpu")
        self.assertIn("only 2.1 GB is free right now", str(caught.exception))
        self.assertEqual(self.ops(), [])  # nothing was loaded
        self.assertFalse(omni_engine.running())
        self.assertTrue(engines.passing(str(caught.exception)))  # a failure of the moment, not of this PC
        self.free = 0.0  # cannot be read: then it is simply tried
        self.assertEqual(self.speak("torch-cpu")["audio"], 2.0)

    def test_a_helper_that_is_already_running_is_not_second_guessed(self):
        self.speak()
        self.free = 0.5  # its memory is already taken, by itself
        self.assertEqual(self.speak()["audio"], 2.0)

    def test_a_recording_with_no_words_is_refused(self):
        self.mode("silent_voice")
        with self.assertRaises(UserError) as caught:
            self.speak()
        self.assertIn("could not make out any words", str(caught.exception))
        self.assertEqual(store.read(paths.HEARD, {}), {})

    def test_cancel_stops_the_helper_at_once(self):
        self.speak()
        self.mode("slow")
        stop = threading.Event()
        threading.Timer(0.6, stop.set).start()
        t0 = time.time()
        with self.assertRaises(Cancelled):
            self.speak(cancelled=stop.is_set)
        self.assertLess(time.time() - t0, 10)
        self.assertFalse(omni_engine.running())
        self.mode("ok")
        self.assertEqual(self.speak()["audio"], 2.0)

    def test_the_self_test_listens_again_and_times_the_speaking_not_the_start(self):
        store.write(paths.HEARD, {omni_engine._voice_key(VOICE): "stale words from before"})
        test = omni_engine.self_test("torch-cu128")
        self.assertEqual(test, {"ok": True, "per10": 2.5})  # 0.5 s of work for 2 s of voice
        self.assertEqual(self.ops(), ["hear", "speak", "speak"])  # quick, so it is timed twice
        self.assertEqual(list(store.read(paths.HEARD, {}).values()), ["what the recording says"])

    def test_another_model_speaking_closes_the_helper_first(self):
        self.speak()
        self.assertTrue(omni_engine.running())
        with mock.patch.object(engines.subprocess, "Popen", side_effect=OSError("not run in this test")):
            with self.assertRaises(OSError):
                engines.speak("cuda13", "chatterbox", "hello", self.out, VOICE, "en")
        self.assertFalse(omni_engine.running())


class Setup(unittest.TestCase):
    """Setting up OmniVoice's Python goes on from the step it stopped in."""

    RT = "torch-cu128"

    def setUp(self):
        paths.ensure()
        import shutil

        shutil.rmtree(omni_engine.runtime_dir(self.RT), ignore_errors=True)
        self.addCleanup(shutil.rmtree, omni_engine.runtime_dir(self.RT), True)
        self.fetched: list[str] = []
        self.pips: list[list] = []
        self.fail_packages = False

        def fake_fetch(url, dest, *a, **k):
            self.fetched.append(url.rsplit("/", 1)[1].split("-")[0])
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"x")

        def fake_pip(rt, args, job, log, on_line=None):
            self.pips.append([str(a) for a in args])
            if "-r" in args:
                if self.fail_packages:
                    raise UserError("The Python packages could not be downloaded.")
                return
            lib = omni_engine.runtime_dir(rt) / "python" / "Lib" / "site-packages" / "torch" / "lib"
            lib.mkdir(parents=True, exist_ok=True)
            (lib / "dnnl.lib").write_bytes(b"x")
            (lib / "torch_cpu.dll").write_bytes(b"x")

        class FakeTar:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def extractall(self, target, **k):
                (Path(target) / "python").mkdir(parents=True)
                (Path(target) / "python" / "python.exe").write_bytes(b"x")

        for p in (mock.patch.object(omni_engine, "fetch", fake_fetch), mock.patch.object(omni_engine, "_pip", fake_pip),
                  mock.patch.object(omni_engine.tarfile, "open", lambda *a, **k: FakeTar())):  # fmt: skip
            p.start()
            self.addCleanup(p.stop)

    def install(self):
        from jobs import Job

        omni_engine.install_runtime(self.RT, Job("install", "test"), 0.0, 1.0)

    def test_a_fresh_setup_does_all_three_steps_and_drops_the_dead_weight(self):
        self.install()
        self.assertEqual(self.fetched, ["cpython", "torch", "torchaudio"])
        self.assertEqual(len(self.pips), 2)
        self.assertIn("--require-hashes", self.pips[1])
        self.assertTrue(omni_engine.runtime_ready(self.RT))
        lib = omni_engine.runtime_dir(self.RT) / "python" / "Lib" / "site-packages" / "torch" / "lib"
        self.assertEqual(sorted(f.name for f in lib.iterdir()), ["torch_cpu.dll"])  # the .lib files are for C++ programmers
        self.assertEqual([f.name for f in paths.DOWNLOADS.glob("torch*")], [])  # and the download is not kept
        self.assertEqual(omni_engine.disk_needed(self.RT), 0)

    def test_after_a_lost_connection_pytorch_is_not_fetched_again(self):
        self.fail_packages = True
        with self.assertRaises(UserError):
            self.install()
        self.assertFalse(omni_engine.runtime_ready(self.RT))
        self.fetched.clear()
        self.pips.clear()
        self.fail_packages = False
        self.install()
        self.assertEqual(self.fetched, [])  # neither Python nor the 3 GB of PyTorch
        self.assertEqual(len(self.pips), 1)
        self.assertTrue(omni_engine.runtime_ready(self.RT))

    def test_installing_another_model_meanwhile_does_not_throw_the_half_done_setup_away(self):
        # Found by doing it: OmniVoice's Python was fetched (3 GB), Chatterbox was installed
        # next, and its clean-up of unused engines deleted what had just been downloaded.
        self.fail_packages = True
        with self.assertRaises(UserError):
            self.install()
        store.write(paths.INSTALLED, {"models": {"chatterbox": {"runtime": "cuda13"}}, "tried": {}})
        engines._drop_unused_runtimes()
        self.assertTrue(omni_engine._done(self.RT, "TORCH"))  # still there
        self.fail_packages = False
        self.fetched.clear()
        self.install()
        self.assertEqual(self.fetched, [])
        # once it is complete and no installed model uses it, it does go
        engines._drop_unused_runtimes()
        self.assertFalse(omni_engine.runtime_dir(self.RT).exists())

    def test_a_setup_that_is_ready_is_left_alone(self):
        self.install()
        self.fetched.clear()
        self.install()
        self.assertEqual(self.fetched, [])

    def test_a_folder_too_deep_for_windows_is_said_before_anything_is_downloaded(self):
        deep = Path("C:/Users/A Rather Long User Name/OneDrive - Some Company/Desktop/New folder (2)/hunter-tts-lab-main/hunter-tts-lab-main/data/runtimes")
        with mock.patch.object(omni_engine, "runtime_dir", lambda rt: deep / rt), mock.patch.object(omni_engine, "_long_paths_on", lambda: False):
            self.assertTrue(omni_engine.path_too_deep(self.RT))
            with self.assertRaises(UserError) as caught:
                self.install()
            self.assertIn("somewhere shorter", str(caught.exception))
            self.assertEqual(self.fetched, [])
        # the usual place, a Downloads folder, is fine
        usual = Path("C:/Users/Rahul Kumar/Downloads/hunter-tts-lab-main/hunter-tts-lab-main/data/runtimes")
        with mock.patch.object(omni_engine, "runtime_dir", lambda rt: usual / rt), mock.patch.object(omni_engine, "_long_paths_on", lambda: False):
            self.assertFalse(omni_engine.path_too_deep(self.RT))
        # and a PC with long paths switched on has no such limit
        with mock.patch.object(omni_engine, "runtime_dir", lambda rt: deep / rt), mock.patch.object(omni_engine, "_long_paths_on", lambda: True):
            self.assertFalse(omni_engine.path_too_deep(self.RT))

    def test_disk_needed_counts_the_download_and_its_unpacked_copy(self):
        gb = omni_engine.disk_needed(self.RT) / 1024**3
        self.assertTrue(10.5 < gb < 12, gb)  # 3.2 GB download + 6.9 GB unpacked + 1 GB
        self.assertTrue(4 < omni_engine.disk_needed("torch-cpu") / 1024**3 < 5)


if __name__ == "__main__":
    unittest.main()
