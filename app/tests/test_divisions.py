"""Divisions are the owner's data: the code never names a person."""

import pathlib
import re

from cos import db, store
from cos.importer import import_page

CORE = pathlib.Path(__file__).resolve().parents[1] / "cos"


def test_owner_division_and_fallback(tmp_path):
    c = db.connect(tmp_path / "cos.db")
    assert store.owner_division(c) == "me"  # nothing set yet
    store.put_setting(c, "divisions", {"alex": {"label": "Alex"}, "home": {"label": "Home"}})
    assert store.owner_division(c) == "alex"  # no "me": the first division
    store.put_setting(c, "schedule", {"division": "home"})
    assert store.owner_division(c) == "home"
    assert store.division_or_owner(c, "alex") == "alex" and store.division_or_owner(c, "nobody") == "home"
    c.close()


def test_page_import_uses_the_configured_names(tmp_path):
    c = db.connect(tmp_path / "cos.db")
    store.put_setting(c, "divisions", {"me": {}, "kids": {}})
    import_page(c, {"settings": {"agentName": "Juno"},
                    "items": [{"id": "a", "title": "x", "division": "kids"}, {"id": "b", "title": "y", "division": "someone"}],
                    "messages": [{"id": "1", "from": "juno", "text": "hi"}, {"id": "2", "from": "pat", "text": "yo"}]})
    assert store.get_item(c, "page-a")["division"] == "kids" and store.get_item(c, "page-b")["division"] == "me"
    assert {m["text"]: m["from"] for m in store.list_messages(c)} == {"hi": "assistant", "yo": "owner"}
    c.close()


def test_no_personal_names_in_the_core_code():
    names = re.compile(r"\b(andrew|stephanie|micah|tiffany|tower)\b", re.I)
    hits = [f"{p.relative_to(CORE)}:{i}" for p in CORE.rglob("*") if p.suffix in {".py", ".js", ".html"}
            for i, line in enumerate(p.read_text().splitlines(), 1) if names.search(line)]
    assert hits == []
