from topwords.core import top_words


def test_ties_are_alphabetical():
    assert top_words("b a", 2) == ["a", "b"]
