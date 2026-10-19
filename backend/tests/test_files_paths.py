import pytest

from farm.api.files import ROOT, clean_path, parse_ls


@pytest.mark.parametrize("raw,want", [
    (None, ROOT), ("", ROOT), ("/sdcard", ROOT), ("/sdcard/", ROOT),
    ("DCIM/Camera", "/sdcard/DCIM/Camera"),
    ("/storage/emulated/0/Download//a.jpg", "/sdcard/Download/a.jpg"),
    ("/sdcard/./Pictures", "/sdcard/Pictures"),
])
def test_clean_ok(raw, want):
    assert clean_path(raw) == want


@pytest.mark.parametrize("raw", [
    "/sdcard/../data", "../etc", "/data/data/x", "/sdcard2/x", "/sdcard/a\nb",
    "/sdcard/a\x00b", "/system/bin", "/sdcard/a/../../x",
])
def test_clean_bad(raw):
    with pytest.raises(ValueError):
        clean_path(raw)


def test_parse_ls():
    out = ("drwxrwx--x 4 u0_a1 media_rw 3452 2024-05-01 10:22 DCIM\n"
           "-rw-rw---- 1 u0_a1 media_rw 120 2024-05-02 11:00 my photo.jpg\n"
           "-rw-rw---- root sdcard_rw 5 2020-01-01 10:00 old.txt\n"
           "total 8\n")
    items = parse_ls(out, "/sdcard")
    assert [(i["name"], i["dir"], i["size"]) for i in items] == [
        ("DCIM", True, 3452), ("my photo.jpg", False, 120), ("old.txt", False, 5)]
    assert items[1]["path"] == "/sdcard/my photo.jpg"
