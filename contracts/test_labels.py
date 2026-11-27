import sys
import unittest

sys.path.insert(0, "classify")
from classify import label  # noqa: E402


class LabelsContract(unittest.TestCase):
    """What report relies on: any number gets "high" or "low", negative ones included."""

    def test_every_number_gets_a_label(self):
        for x in (-5, 0, 3.5, 49, 50, 1000):
            self.assertIn(label(x), ("high", "low"))


if __name__ == "__main__":
    unittest.main()
