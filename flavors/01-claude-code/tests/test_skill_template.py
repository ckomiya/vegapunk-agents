# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Christian Gonzales Komiya
"""A net against drift between the /vegapunk skill and punk_records.py.

It reads the generated SKILL.md; it does not test how a model behaves.
"""
from __future__ import annotations

import argparse
import re
import sys
import unittest
from pathlib import Path

CLAUDE_DIR = Path(__file__).resolve().parent.parent / ".claude"
sys.path.insert(0, str(CLAUDE_DIR / "vegapunk"))
try:
    import punk_records
finally:
    sys.path.remove(str(CLAUDE_DIR / "vegapunk"))

# Subcommands neither Stella nor the engine uses (read-only ones could be listed here).
UNUSED_SUBCOMMANDS: set[str] = set()


def subcommands() -> dict[str, argparse.ArgumentParser]:
    parser = punk_records.build_parser()
    return next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction)).choices


class SkillTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        text = (CLAUDE_DIR / "skills" / "vegapunk" / "SKILL.md").read_text(encoding="utf-8")
        # Only the engine's own instructions: the coordinator section is copied from core/
        # and would satisfy these checks by itself.
        cls.engine, marker, _ = text.partition("# Coordinator conduct toward Stella")
        assert marker, "coordinator section not found"

    def test_mentions_the_0_3_cycle(self):
        for term in ("`decide", "`--research-rounds`", "`flag", "`ops_not_ready`", "`refusal`", "`incomplete`"):
            with self.subTest(term=term):
                self.assertIn(term, self.engine)

    def test_every_subcommand_appears(self):
        for name in set(subcommands()) - UNUSED_SUBCOMMANDS:
            with self.subTest(subcommand=name):
                self.assertRegex(self.engine, rf"`{re.escape(name)}[` ]")

    def test_every_decision_appears(self):
        decide = subcommands()["decide"]
        choices = next(a.choices for a in decide._actions if a.dest == "decision")
        for choice in choices:
            with self.subTest(decision=choice):
                self.assertIn(f"decide --decision {choice}", self.engine)


if __name__ == "__main__":
    unittest.main()
