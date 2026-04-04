from __future__ import annotations

import asyncio
import unittest

from simulation.demo_verbose_cycle import run_demo_cycle


class VerboseDemoCycleTests(unittest.TestCase):
    def test_verbose_demo_cycle_runs_end_to_end(self) -> None:
        result = asyncio.run(run_demo_cycle(emit=False))

        self.assertEqual(
            result["tool_sequence"],
            [
                "status__whoami",
                "tool_ops__capability_snapshot",
                "jobs__create",
                "cap__get_report",
                "tool_ops__job_digest",
            ],
        )
        self.assertIn("report demo-42", result["final_response"])
        self.assertEqual(len(result["provider_calls"]), 1)
        self.assertTrue(result["provider_calls"][0]["url"].endswith("/reports/demo-42"))
        self.assertEqual(result["jobs"][0]["status"], "completed")
        self.assertEqual(result["metrics"]["completed_jobs"], 1)


if __name__ == "__main__":
    unittest.main()
