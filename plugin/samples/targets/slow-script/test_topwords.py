"""Behaviour that any faster version must keep. Part of the judge's harness."""

import unittest

from topwords import top_words


class TopWords(unittest.TestCase):
    def test_counts_and_order(self):
        self.assertEqual(top_words("b a b c a b", 2), [("b", 3), ("a", 2)])

    def test_ties_are_alphabetical(self):
        self.assertEqual(top_words("z y x", 3), [("x", 1), ("y", 1), ("z", 1)])

    def test_case_and_punctuation(self):
        self.assertEqual(top_words("Cat, cat. CAT! dog?", 2), [("cat", 3), ("dog", 1)])

    def test_k_larger_than_vocabulary(self):
        self.assertEqual(top_words("one two", 10), [("one", 1), ("two", 1)])

    def test_empty(self):
        self.assertEqual(top_words("", 3), [])
        self.assertEqual(top_words("... ,,, !!", 3), [])


if __name__ == "__main__":
    unittest.main()
