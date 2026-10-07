"""Exhaustive new-course contracts plus read-only compatibility of existing learning IDs."""

from html import escape
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from services import anatomy_miniapp as course
from web_api import static_content
from web_api.tests.test_static_content import FakeTb
from web_api.routers.subjects import _check_anatomy_material_access, _anatomy_module_locked_reason


@pytest.mark.parametrize("topic_id", list(course.TOPICS))
def test_all_imported_topics_have_complete_safe_text_and_navigation(topic_id):
    topic = course.TOPICS[topic_id]
    data = topic["data"]
    result = static_content.get_material(FakeTb(anatomy={"present": {}}), "anatomy", "course", topic_id)
    assert result["title"] == data["name"]
    assert result["media"] == []
    for block in data["theory"]:
        if block["t"] == "p":
            assert escape(block["x"]).replace("\n", "<br>") in result["content_html"]
        else:
            assert all(escape(item) in result["content_html"] for item in block["items"])
    assert "<img" not in result["content_html"]
    for key, reverse in [("next_id", "prev_id"), ("prev_id", "next_id")]:
        if result[key]:
            assert course.material(result[key])[reverse] == topic_id
    assert topic_id in [item["id"] for item in course.group_detail(result["group_id"])["items"]]


def test_source_hierarchy_assigns_each_topic_exactly_once():
    assert [course.GROUPS[gid]["title"] for gid in course.COURSE["roots"]] == [
        "Остеология",
        "Синдесмология",
        "Миология",
        "Спланхнология",
        "Неврология",
        "Ангиология",
    ]
    ids = [tid for gid in course.COURSE["roots"] for tid in course.GROUPS[gid]["ids"]]
    assert len(ids) == len(set(ids)) == 143
    assert sum(len(course.GROUPS[gid]["sections"]) for gid in course.COURSE["roots"]) == 31
    assert [course.GROUPS[gid]["title"] for gid in course.GROUPS["anatomapp_m6"]["subgroups"]] == [
        "ЦНС",
        "ПНС",
        "Органы чувств",
    ]
    for group in course.GROUPS.values():
        assert [tid for section in group["sections"] for tid in section["ids"]] == group["ids"]


@pytest.mark.parametrize("topic_id", list(course.TOPICS))
def test_imported_material_uses_existing_subscription_and_maintenance_gates(topic_id):
    topic = course.TOPICS[topic_id]
    permission = course.GROUPS[topic["module_id"]]["permission_key"]
    seen = []
    tb = SimpleNamespace(
        ANATOMY={},
        stats={},
        anatomy_maintenance_mode_enabled=lambda: False,
        is_admin_or_assistant=lambda uid: False,
        anatomy_section_access_ok=lambda uid, key: (
            seen.append(key) or key not in ("module7_nervous", "module8_cardiovascular")
        ),
        cheapest_anatomy_tier=lambda: {"short": "Базовый", "price_rub": 100, "price_stars": 100},
    )
    if permission in ("module7_nervous", "module8_cardiovascular"):
        with pytest.raises(HTTPException) as error:
            _check_anatomy_material_access(tb, 123, "course", topic_id)
        assert error.value.status_code == 403
    else:
        _check_anatomy_material_access(tb, 123, "course", topic_id)
    assert seen == [permission]
    tb.anatomy_maintenance_mode_enabled = lambda: True
    with pytest.raises(HTTPException) as error:
        _check_anatomy_material_access(tb, 123, "course", topic_id)
    assert error.value.status_code == 403


def test_neurology_children_cannot_bypass_paid_parent_gate():
    tb = SimpleNamespace(
        stats={},
        anatomy_maintenance_mode_enabled=lambda: False,
        anatomy_section_access_ok=lambda uid, key: key != "module7_nervous",
        cheapest_anatomy_tier=lambda: {"short": "Базовый", "price_rub": 100, "price_stars": 100},
    )
    for gid in course.GROUPS["anatomapp_m6"]["subgroups"]:
        assert _anatomy_module_locked_reason(tb, 123, gid)


def test_legacy_materials_and_learning_records_survive_course_import(monkeypatch, tmp_path):
    import json
    from web_api import learning

    legacy = json.loads(open("anatomy.json", encoding="utf-8").read())
    tb = FakeTb(anatomy=legacy)
    monkeypatch.setenv("MINIAPP_LEARNING_DB", str(tmp_path / "learning.sqlite3"))
    old_ids = [tid for module in legacy.values() for tid in module["topics"]]
    for tid in old_ids:
        result = static_content.get_material(tb, "anatomy", "course", tid)
        assert result["title"]
    tid = old_ids[0]
    learning.touch_material(
        42,
        {
            "subject_id": "anatomy",
            "section_id": "course",
            "material_id": tid,
            "material_title": "Старая тема",
            "material_order": 1,
            "total_in_section": 8,
        },
    )
    learning.set_material_flag(42, "anatomy", "course", tid, "completed", True)
    learning.set_material_flag(42, "anatomy", "course", tid, "favorite", True)
    before = learning.get_state(42)
    for imported in course.TOPICS:
        course.material(imported)
    assert learning.get_state(42) == before
