import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout, closing
from io import StringIO

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


worker = load("wuxing_backfill", "脚本/补全五行画像.py")
overlay = load("wuxing_overlay_test", "汉字五行知识库/model_overlay.py")


def job(char):
    return {"char": char, "input_hash": char, "citations": [{"id": "q1", "text": "原文", "source": "资料"}]}


def result(char):
    return {"char": char, "status": "scored", "scores": {"金": 0, "木": 0, "水": 0, "火": 0, "土": 100},
            "explanation": "结合所给字义资料，以承载包容之意取土，仅为传统取象推断。", "evidence_ids": ["q1"]}


def bundle(chars):
    return {"base_sha256": "test-base", "prompt_version": worker.PROMPT_VERSION,
            "existing": 2292, "jobs": [job(c) for c in chars]}


class BackfillTests(unittest.TestCase):
    def test_prepare_skips_supported_keeps_placeholders_and_preserves_all_quotes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            knowledge = {"居": {"energy_profile": {"supported": True}},
                         "缺": {"sources": [{"book": "甲", "quote": "全文"}],
                                "energy_profile": {"supported": False, "scores": {"土": 85, "金": 15}}}}
            raw = [{"c": "缺", "en": [{"s": "乙", "t": "长引文" * 5000}], "sw": "说文原文", "hp": [{"gloss": "释义"}]}]
            (root / "kb.json").write_bytes(worker.encoded(knowledge))
            (root / "raw.json").write_bytes(worker.encoded(raw))
            report = worker.prepare(root / "kb.json", root / "raw.json", root / "input.json")
            payload = json.loads((root / "input.json").read_text(encoding="utf-8"))
            self.assertEqual((report["existing"], report["pending"]), (1, 1))
            self.assertEqual(payload["jobs"][0]["char"], "缺")
            texts = [c["text"] for c in payload["jobs"][0]["citations"]]
            self.assertIn("长引文" * 5000, texts)
            self.assertIn("说文原文", texts)
            self.assertEqual(payload["base_sha256"], hashlib.sha256((root / "kb.json").read_bytes()).hexdigest())

    def test_validation_rejects_bad_scores_and_invented_citations(self):
        original = result("清")
        mutations = [dict(scores={"金": 0, "木": 0, "水": 0, "火": 0, "土": 99}),
                     dict(scores={"金": False, "木": 0, "水": 0, "火": 0, "土": 100}),
                     dict(evidence_ids=["q999"]), dict(char="李"), dict(status="insufficient")]
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                worker.validate_result({**original, **mutation}, job("清"))
        no_data = worker.validate_result({**original, "status": "insufficient", "scores": None}, job("清"))
        self.assertEqual(no_data["status"], "insufficient")

    def test_known_nesting_error_is_recovered_without_rescoring_or_rewriting(self):
        expected = result("清")
        nested = {"char": "清", "status": "scored", "scores": {
            **expected["scores"], "explanation": expected["explanation"], "evidence_ids": expected["evidence_ids"]}}
        self.assertEqual(worker.validate_result(nested, job("清")), expected)
        with self.assertRaises(ValueError):
            worker.validate_result({**nested, "explanation": "冲突的解释不能自动采用另一个解释"}, job("清"))

    def test_concurrency_is_bounded_and_resume_never_repeats_completed_characters(self):
        state = {"active": 0, "peak": 0, "seen": []}
        lock = threading.Lock()

        def transport(batch):
            with lock:
                state["active"] += 1
                state["peak"] = max(state["peak"], state["active"])
                state["seen"].extend(j["char"] for j in batch)
            time.sleep(.04)
            with lock:
                state["active"] -= 1
            return {"characters": [result(j["char"]) for j in batch]}, {"total_tokens": 10}

        chars = "甲乙丙丁戊己庚辛壬癸天地人"
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(StringIO()):
            with self.assertRaises(ValueError):
                worker.Runner(bundle(chars), directory, transport, "test", concurrency=5)
            first = worker.Runner(bundle(chars), directory, transport, "test", concurrency=4, batch_size=1).run(limit=8)
            self.assertEqual((first["scored"], first["pending"]), (8, 5))
            second = worker.Runner(bundle(chars), directory, transport, "test", concurrency=4, batch_size=1).run()
            self.assertEqual(second["scored"], len(chars))
            self.assertEqual(state["peak"], 4)
            self.assertEqual(sorted(state["seen"]), sorted(chars))
            self.assertEqual(second["usage"]["total_tokens"], 130)
            exported = json.loads((Path(directory) / "wuxing_model_profiles.json").read_text(encoding="utf-8"))
            self.assertEqual(exported["profiles"]["甲"]["provenance"]["evidence"][0]["text"], "原文")

    def test_partial_batch_retains_valid_results_and_caps_invalid_attempts(self):
        calls = []

        def transport(batch):
            calls.append(batch)
            return {"characters": [result("甲"), {**result("乙"), "evidence_ids": ["made-up"]}]}, {}

        with tempfile.TemporaryDirectory() as directory, redirect_stdout(StringIO()):
            run = worker.Runner(bundle("甲乙"), directory, transport, "test", concurrency=1, attempts=1).run()
            self.assertEqual((run["scored"], run["failed"]), (1, 1))
            worker.Runner(bundle("甲乙"), directory, transport, "test", concurrency=1, attempts=1).run()
            self.assertEqual(len(calls), 1)
            with closing(sqlite3.connect(Path(directory) / "checkpoint.sqlite3")) as db:
                self.assertEqual(db.execute("SELECT error FROM jobs WHERE char='乙'").fetchone()[0], "invented_evidence")

    def test_fatal_auth_failure_stops_new_requests_without_leaking_error_body(self):
        def transport(batch):
            raise worker.ModelFailure("http_401", fatal=True)
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(StringIO()):
            run = worker.Runner(bundle("甲乙丙丁"), directory, transport, "test", concurrency=1, batch_size=1).run()
            self.assertEqual(run["requests"], 1)
            self.assertEqual(run["state"], "stopped")
            self.assertEqual(run["error"], "http_401")

    def test_partial_response_retries_only_missing_character(self):
        calls = []
        clock = [time.time()]

        def transport(batch):
            calls.append([j["char"] for j in batch])
            return {"characters": [result(j["char"]) for j in (batch[:1] if len(calls) == 1 else batch)]}, {}

        def advance_clock():
            clock[0] += 100
            return clock[0]

        with tempfile.TemporaryDirectory() as directory, redirect_stdout(StringIO()), patch.object(worker.time, "time", advance_clock):
            report = worker.Runner(bundle("甲乙"), directory, transport, "test", concurrency=1, batch_size=2).run()
            self.assertEqual(calls, [["甲", "乙"], ["乙"]])
            self.assertEqual(report["scored"], 2)

    def test_same_checkpoint_refuses_a_second_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "worker.lock"
            with worker.exclusive_lock(lock):
                with self.assertRaises(RuntimeError):
                    with worker.exclusive_lock(lock):
                        self.fail("duplicate worker acquired the lock")

    def test_overlay_never_changes_supported_profiles_or_etymological_classification(self):
        original = {"居": {"element": None, "energy_profile": {"supported": True, "scores": {"木": 50, "土": 50}}},
                    "丕": {"element": None, "sources": [{"book": "说文", "quote": "大也"}], "energy_profile": {"supported": False}}}
        before = copy.deepcopy(original)
        profile = {"supported": True, "scores": result("丕")["scores"], "semantic_notes": "传统取象参考",
                   "provenance": {"kind": "llm_inference"}}
        merged = overlay.merge_profiles(original, {"base_sha256": "test", "profiles": {"居": {}, "丕": profile}}, "test")
        self.assertEqual(original, before)
        self.assertEqual(merged["居"], original["居"])
        self.assertIsNone(merged["丕"]["element"])
        self.assertEqual(merged["丕"]["sources"], original["丕"]["sources"])
        self.assertTrue(merged["丕"]["energy_profile"]["supported"])
        with self.assertRaises(ValueError):
            overlay.merge_profiles(original, {"base_sha256": "different", "profiles": {}}, "test")


if __name__ == "__main__":
    unittest.main()
