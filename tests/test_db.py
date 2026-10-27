import db


def setup_module():
    db.init_db()


def test_mark_seen_and_is_seen():
    assert not db.is_seen("t_1")
    db.mark_seen("t_1", "test", "Flutter Dev", "Acme", "http://x")
    assert db.is_seen("t_1")


def test_content_duplicate():
    db.mark_seen("t_2", "test", "Flutter Dev 2", "Corp", "http://y")
    assert db.is_content_duplicate(" flutter dev 2 ", "CORP")
    assert not db.is_content_duplicate("Other", "Corp")
    assert not db.is_content_duplicate("", "")


def test_manual_vacancy():
    vid = db.add_manual_vacancy("T", "C", "http://z", "", "desc")
    assert vid.startswith("manual_")
    assert db.get_vacancy(vid)["title"] == "T"


def test_toggle_star():
    db.mark_seen("t_3", "test", "A", "B", "http://q")
    assert db.toggle_star("t_3") is True
    assert db.toggle_star("t_3") is False
