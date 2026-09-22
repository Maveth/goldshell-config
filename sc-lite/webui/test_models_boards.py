#!/usr/bin/env python3
"""Unit tests for ProductGuy-adapted models/boards (no miner required)."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from boards import parse_devs4028, summarize_boards
from models import model_key, profile_for
from soft_watchdog import SoftWatchdog

HERE = Path(__file__).resolve().parent
SC5 = HERE / "fixtures" / "sc5proii"


class ModelsTest(unittest.TestCase):
    def test_sc5proii_unicode_key(self):
        status = json.loads((SC5 / "mcb_status.json").read_text(encoding="utf-8"))
        p = profile_for(status["model"])
        self.assertTrue(p["known"])
        self.assertEqual(p["profile_id"], "sc5-pro-ii")
        self.assertEqual(p["boards"], 4)
        self.assertEqual(p["fans"], 4)
        self.assertEqual(p["plan_dialect"], "mv_pv")
        self.assertFalse(p["fan_target"])
        self.assertIn(0, p["plan_names"] or {})

    def test_sclite_key(self):
        p = profile_for("Goldshell-SCLITE")
        self.assertEqual(p["profile_id"], "sc-lite")
        self.assertEqual(p["plan_dialect"], "mv_pv")

    def test_key_normalization(self):
        self.assertEqual(model_key("Goldshell-SC5ProⅡ"), model_key("goldshell sc5proⅱ"))


class BoardsTest(unittest.TestCase):
    def test_sc5_four_boards(self):
        payload = json.loads((SC5 / "api4028_devs.json").read_text(encoding="utf-8"))
        boards = parse_devs4028(payload)
        self.assertEqual(len(boards), 4)
        s = summarize_boards(boards)
        self.assertEqual(s["nboards"], 4)
        self.assertEqual(s["nfans"], 4)
        self.assertIsNotNone(s["chip_temp_hot"])
        self.assertGreater(float(s["mhs_av"] or 0), 0)


class WatchdogTest(unittest.TestCase):
    def test_unreachable_dry_run(self):
        t = [1000.0]

        def clock():
            return t[0]

        dog = SoftWatchdog(
            interval_s=30,
            unreachable_minutes=1,  # ~2 rows
            stall_minutes=10,
            absent_minutes=0,
            min_gap_minutes=0.01,
            dry_run=True,
            clock=clock,
        )
        # enough bad samples to fill unreachable window
        fired = None
        for _ in range(4):
            dog.observe(False, None)
            t[0] += 30
            d = dog.check()
            if d.get("action") == "would_restart":
                fired = d
                break
        self.assertIsNotNone(fired)
        self.assertEqual(fired.get("reason"), "unreachable")


if __name__ == "__main__":
    unittest.main()
