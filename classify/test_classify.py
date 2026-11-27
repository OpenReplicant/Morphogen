import unittest
from classify import label


class Labels(unittest.TestCase):
    def test_labels_are_high_or_low(self):
        self.assertIn(label(3), ("high", "low"))
        self.assertIn(label(300), ("high", "low"))


if __name__ == "__main__":
    unittest.main()
