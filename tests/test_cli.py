from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout

from gpu_priorityd.cli import main


class CLITests(unittest.TestCase):
    def test_simulation_command(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            result = main(["simulate"])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue())["simulation"], "ok")


if __name__ == "__main__":
    unittest.main()

