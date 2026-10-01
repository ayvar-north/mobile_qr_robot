"""Boot journal recovery checks. Run with unittest discover."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scr/pico/firmware"))

from boot_counter import initialize, next_counter


class BootJournalTests(unittest.TestCase):
    def test_initialization_increment_and_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix = os.path.join(directory, "boot")
            with self.assertRaises(RuntimeError):
                next_counter(prefix)
            initialize(prefix)
            with self.assertRaises(RuntimeError):
                initialize(prefix)
            self.assertEqual(next_counter(prefix), 1)
            self.assertEqual(next_counter(prefix), 2)
            # Simulate a torn write to the older slot; the other is valid.
            with open(prefix + "1.dat", "wb") as output:
                output.write(b"00000003:")
            self.assertEqual(next_counter(prefix), 3)


if __name__ == "__main__":
    unittest.main()
