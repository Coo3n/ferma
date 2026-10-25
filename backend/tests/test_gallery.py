"""Галерея готовых сюжетов: карточки из ast, копирование, имена, изоляция."""
import pytest
from fastapi import HTTPException

from farm import config, gallery, scenarios
from farm.api import gallery as api_gallery

CARD = '''"""Лента для проверки."""
NAME = "Лента {n}"
DESCRIPTION = "Листает и лайкает"
GALLERY = {{"platform": "TikTok", "verified": False, "package": "com.x"}}
PARAMS = feed.feed_params()


def run(ctx):
    pass
'''


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    gal, sc = tmp_path / "gallery", tmp_path / "scenarios"
    gal.mkdir()
    sc.mkdir()
    monkeypatch.setattr(config, "GALLERY_DIR", gal)
    monkeypatch.setattr(config, "SCENARIOS_DIR", sc)
    return gal, sc


def put(gal, key, n=1):
    (gal / f"{key}.py").write_text(CARD.format(n=n), "utf-8")


def test_items_read_metadata_without_executing(dirs):
    gal, _ = dirs
    put(gal, "tiktok_feed")                       # PARAMS ссылается на feed, которого в файле нет
    got = gallery.items()
    assert got == [{"key": "tiktok_feed", "name": "Лента 1", "description": "Листает и лайкает",
                    "platform": "TikTok", "verified": False, "package": "com.x", "added": False}]


def test_items_skip_underscore_and_broken_files(dirs):
    gal, _ = dirs
    put(gal, "ok")
    put(gal, "_hidden")
    (gal / "broken.py").write_text("def (:\n", "utf-8")
    (gal / "noname.py").write_text("x = 1\n", "utf-8")
    assert [c["key"] for c in gallery.items()] == ["ok"]


def test_description_falls_back_to_docstring(dirs):
    gal, _ = dirs
    (gal / "d.py").write_text('"""Первая строка.\n\nВторая."""\nNAME = "Д"\n', "utf-8")
    assert gallery.items()[0]["description"] == "Первая строка."


def test_add_copies_file_and_marks_added(dirs):
    gal, sc = dirs
    put(gal, "tiktok_feed")
    key = gallery.add("tiktok_feed")
    assert key == "tiktok_feed"
    assert (sc / "tiktok_feed.py").read_bytes() == (gal / "tiktok_feed.py").read_bytes()
    assert gallery.items()[0]["added"] is True


def test_add_twice_gets_numbered_name(dirs):
    gal, sc = dirs
    put(gal, "tiktok_feed")
    assert gallery.add("tiktok_feed") == "tiktok_feed"
    assert gallery.add("tiktok_feed") == "tiktok_feed_2"
    assert gallery.add("tiktok_feed") == "tiktok_feed_3"
    assert sorted(p.name for p in sc.glob("*.py")) == ["tiktok_feed.py", "tiktok_feed_2.py", "tiktok_feed_3.py"]


@pytest.mark.parametrize("bad", ["../etc", "a/b", "A", "", "x.py", "nope"])
def test_add_rejects_bad_or_unknown_keys(dirs, bad):
    with pytest.raises(KeyError):
        gallery.add(bad)


def test_gallery_files_are_not_in_my_scenarios(dirs):
    gal, sc = dirs
    put(gal, "tiktok_feed")
    assert scenarios.discover(force=True) == []


def test_api_list_and_add(dirs):
    gal, _ = dirs
    put(gal, "tiktok_feed")
    assert api_gallery.list_gallery()[0]["key"] == "tiktok_feed"
    assert api_gallery.add_to_mine("tiktok_feed") == {"key": "tiktok_feed"}


def test_api_add_unknown_is_404(dirs):
    with pytest.raises(HTTPException) as e:
        api_gallery.add_to_mine("nope")
    assert e.value.status_code == 404
