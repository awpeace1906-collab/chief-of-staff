"""Divisions are the owner's data: the code never names a person."""

import pathlib

from cos import db, store
from cos.importer import import_page

REPO = pathlib.Path(__file__).resolve().parents[2]
CORE = REPO / "app" / "cos"


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
    """The core code holds nobody's information: run the guard over app/cos with the example memory's
    names (and, when COS_MEMORY_DIR points at a real memory, over the whole repo with that one)."""
    import json
    import os
    import sys
    sys.path.insert(0, str(REPO / "tools"))
    import check_core

    example = json.loads((REPO / "examples" / "memory" / "memory.json").read_text())
    assert check_core.scan(CORE, check_core.personal_terms(example)) == []
    real = os.environ.get("COS_MEMORY_DIR")
    if real:
        terms = check_core.personal_terms(json.loads((pathlib.Path(real) / "memory.json").read_text()))
        assert check_core.scan(REPO, terms, {pathlib.Path(real).resolve()}) == []


def test_the_guard_finds_what_memory_names(tmp_path):
    import sys
    sys.path.insert(0, str(REPO / "tools"))
    import check_core

    (tmp_path / "a.md").write_text("Ask Alex about it.\nMail alex@example.org\nNothing here.\n")
    terms = check_core.personal_terms({"assistant": {"name": "Juno", "email": "alex@example.org"},
                                       "people": [{"name": "Alex Doe"}]})
    assert check_core.scan(tmp_path, terms) == ["a.md:1: Alex", "a.md:2: alex@example.org"]
