import json
import tempfile
import unittest
from pathlib import Path

from gaokao_top_rankings_1996_2026.scripts.normalize_source import DEFAULT_INPUT, normalize
from 脚本.导入高考状元来源 import BOOK_NAME, 读取高考资料, _payload


class GaokaoSourceTests(unittest.TestCase):
    def test_normalized_source_keeps_range_subject_and_given_name_contract(self):
        rows, manifest = normalize(DEFAULT_INPUT)
        self.assertEqual(manifest["year_start"], 1996)
        self.assertEqual(manifest["year_end"], 2026)
        self.assertIn("文科", manifest["subjects"])
        self.assertIn("理科", manifest["subjects"])
        self.assertEqual(len(rows), 1947)
        self.assertEqual(len({row["given_name"] for row in rows}), 1560)
        self.assertTrue(all(1996 <= row["year"] <= 2026 for row in rows))
        self.assertIn(2026, {row["year"] for row in rows})
        self.assertTrue(all(len(row["given_name"]) in {1, 2} for row in rows))
        self.assertIn("欧阳觅剑", {row["full_name"] for row in rows})
        self.assertNotIn("张杨子苏", {row["full_name"] for row in rows})

    def test_normalized_json_matches_manifest(self):
        data = 读取高考资料()
        self.assertEqual(data["manifest"]["accepted_rows"], len(data["rows"]))
        self.assertEqual(data["manifest"]["unique_given_names"], len({row["given_name"] for row in data["rows"]}))

    def test_payload_preserves_year_province_subject_and_all_ties(self):
        rows, _ = normalize(DEFAULT_INPUT)
        same = [row for row in rows if row["given_name"] == rows[0]["given_name"]]
        payload = _payload(same[0]["given_name"], same[0], 42, same)
        self.assertEqual(payload["书名"], BOOK_NAME)
        self.assertEqual(payload["来源片段编号"], 42)
        self.assertEqual(len(payload["高考来源"]), len(same))
        self.assertIn(same[0]["subject"], payload["方向"])

    def test_rejects_tampered_manifest_or_out_of_contract_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text(json.dumps({"manifest": {"year_start": 1995, "year_end": 2026,
                "subjects": ["文科", "理科"], "accepted_rows": 0}, "rows": []}), encoding="utf-8")
            with self.assertRaises(ValueError):
                读取高考资料(path)


if __name__ == "__main__":
    unittest.main()
