from parsers.filter import is_relevant


def test_keyword_match():
    assert is_relevant("Senior Flutter developer")


def test_no_keyword():
    assert not is_relevant("Python backend engineer")


def test_empty():
    assert not is_relevant("", "")


def test_stopword_rejects():
    assert not is_relevant("Flutter, React Native only")


def test_multiple_fields():
    assert is_relevant("Вакансия", "требуется Dart-разработчик")
