"""docs/public-api.md не врёт: каждый упомянутый маршрут существует в ферме."""
import re
from pathlib import Path

from farm.server import create_app

DOC = Path(__file__).resolve().parents[2] / "docs" / "public-api.md"
ROW = re.compile(r"^\|\s*`(GET|POST|PUT|PATCH|DELETE) (/api/[^`]+)`", re.M)


def _paths():
    return create_app().openapi()["paths"]


def test_doc_exists_and_has_routes():
    assert DOC.is_file()
    assert len(ROW.findall(DOC.read_text("utf-8"))) >= 10


def test_every_documented_route_exists():
    paths = _paths()
    missing = []
    for method, path in ROW.findall(DOC.read_text("utf-8")):
        if method.lower() not in paths.get(path, {}):
            missing.append(f"{method} {path}")
    assert not missing, f"в документе есть несуществующие маршруты: {missing}"


def test_doc_explains_token_and_address():
    text = DOC.read_text("utf-8")
    assert "FARM_TOKEN" in text and "X-Farm-Token" in text and "127.0.0.1:8777" in text
