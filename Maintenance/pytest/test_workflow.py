
import pytest
from Maintenance.backend.database import init_db, connect
from Maintenance.backend.services import (
    create_ticket, update_ticket, tenant_confirm, get_landlord_tickets,
    get_tenant_tickets, get_ticket_events, find_possible_duplicates,
)


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    import Maintenance.backend.database as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")

    import Maintenance.backend.services as service
    monkeypatch.setattr(service, "connect", db.connect)

    init_db()


def test_ticket_metadata_is_attached_from_lease():
    ticket_id, triage = create_ticket(
        1, 1, "UNIT", None, "Bathroom pipe leaking"
    )

    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM maintenance_tickets WHERE ticket_id=?",
            (ticket_id,)
        ).fetchone()

    assert row["tenant_id"] == 1
    assert row["unit_id"] == 1
    assert row["building_id"] == 1
    assert row["landlord_id"] == 1
    assert triage["category"] == "Plumbing"


def test_tenant_cannot_attach_another_tenants_unit():
    with pytest.raises(PermissionError):
        create_ticket(2, 1, "UNIT", None, "Please repair this")


def test_safety_issue_is_urgent():
    _, triage = create_ticket(
        1, 1, "UNIT", None, "I smell gas in the kitchen"
    )

    assert triage["safety"] is True
    assert triage["urgency"] == "URGENT"


def test_workflow_and_tenant_confirmation():
    ticket_id, _ = create_ticket(
        1, 1, "UNIT", None, "Tap is leaking"
    )

    update_ticket(ticket_id, 1, 1, "ACKNOWLEDGED")
    update_ticket(ticket_id, 1, 1, "IN_PROGRESS")

    with pytest.raises(ValueError):
        update_ticket(ticket_id, 1, 1, "RESOLVED", "")

    update_ticket(
        ticket_id, 1, 1, "RESOLVED", "Replaced washer"
    )
    tenant_confirm(ticket_id, 1, True)

    with connect() as conn:
        status = conn.execute(
            "SELECT status FROM maintenance_tickets WHERE ticket_id=?",
            (ticket_id,)
        ).fetchone()[0]

    assert status == "CLOSED"


def test_landlord_cannot_see_other_landlords_tickets():
    create_ticket(1, 1, "UNIT", None, "Tap leaking")
    assert len(get_landlord_tickets(2)) == 0


def test_jev_request_uses_maintenance_categories_and_priority(monkeypatch):
    import Maintenance.backend.services as service

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "model": "jev-1.14.0",
                "answers": {
                    "categories": {
                        "type": "choice",
                        "choice": "Plumbing",
                        "confidence": 0.99,
                        "probabilities": {
                            "Plumbing": 0.99,
                            "Other": 0.01
                        }
                    },
                    "priority": {
                        "type": "score",
                        "score": 0.73,
                        "confidence": 0.90,
                        "legend": {
                            "0": "low",
                            "1": "normal",
                            "2": "urgent"
                        },
                        "probabilities": {
                            "0": 0.05,
                            "1": 0.90,
                            "2": 0.05
                        }
                    }
                }
            }

    captured = {}

    def fake_post(**kwargs):
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setenv(
        "JEV_BASE_URL",
        "https://jev.example.test/classify"
    )
    monkeypatch.setenv("JEV_API_KEY", "test-key")
    monkeypatch.setattr(service.httpx, "post", fake_post)

    result = service.jev_categorization(
        "Bathroom pipe is leaking",
        "Pipe leak"
    )

    assert result["classification_source"] == "JEV"
    assert result["category"] == "Plumbing"
    assert result["urgency"] == "NORMAL"

    assert captured["json"]["model"] == "jev-latest"
    assert captured["json"]["questions"]["categories"]["type"] == "choice"
    assert captured["json"]["questions"]["priority"]["criteria"] == [
        "low", "normal", "urgent"
    ]


def test_ticket_attachment_is_saved_and_scoped_to_tenant():
    from Maintenance.backend.services import get_ticket_attachments

    attachment = {
        "filename": "leak.jpg",
        "mime_type": "image/jpeg",
        "media_type": "image",
        "data": b"fake-image-bytes"
    }

    ticket_id, _ = create_ticket(
        1, 1, "UNIT", None, "Bathroom pipe leaking",
        attachments=[attachment]
    )

    saved = get_ticket_attachments(ticket_id, tenant_id=1)

    assert len(saved) == 1
    assert saved[0]["filename"] == "leak.jpg"
    assert bytes(saved[0]["data"]) == b"fake-image-bytes"

    with pytest.raises(PermissionError):
        get_ticket_attachments(ticket_id, tenant_id=2)


def test_jev_safety_override_forces_urgent(monkeypatch):
    import Maintenance.backend.services as service

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "model": "jev-1.14.0",
                "answers": {
                    "categories": {
                        "type": "choice",
                        "choice": "Electrical",
                        "confidence": 0.99,
                        "probabilities": {
                            "Electrical": 0.99,
                            "Other": 0.01
                        }
                    },
                    "priority": {
                        "type": "score",
                        "score": 0.20,
                        "confidence": 0.90,
                        "legend": {
                            "0": "low",
                            "1": "normal",
                            "2": "urgent"
                        },
                        "probabilities": {
                            "0": 0.90,
                            "1": 0.05,
                            "2": 0.05
                        }
                    }
                }
            }

    monkeypatch.setenv(
        "JEV_BASE_URL",
        "https://jev.example.test/classify"
    )
    monkeypatch.setenv("JEV_API_KEY", "test-key")
    monkeypatch.setattr(
        service.httpx,
        "post",
        lambda **kwargs: FakeResponse()
    )

    result = service.jev_categorization(
        "There is sparking from the switchboard"
    )

    assert result["category"] == "Electrical"
    assert result["safety"] is True
    assert result["urgency"] == "URGENT"



def test_unit_request_is_saved_as_unit_only():
    ticket_id, _ = create_ticket(
        1, 1, "UNIT", None, "Bedroom light is not working"
    )
    with connect() as conn:
        row = conn.execute(
            "SELECT area_type, unit_id, common_area_name FROM maintenance_tickets WHERE ticket_id=?",
            (ticket_id,)
        ).fetchone()
    assert row["area_type"] == "UNIT"
    assert row["unit_id"] == 1
    assert row["common_area_name"] is None


def test_common_area_request_is_saved_without_unit():
    ticket_id, _ = create_ticket(
        1, None, "COMMON_AREA", "Lift lobby",
        "The lift lobby light is not working",
        common_building_id=1
    )
    with connect() as conn:
        row = conn.execute(
            "SELECT area_type, unit_id, common_area_name, building_id FROM maintenance_tickets WHERE ticket_id=?",
            (ticket_id,)
        ).fetchone()
    assert row["area_type"] == "COMMON_AREA"
    assert row["unit_id"] is None
    assert row["common_area_name"] == "Lift lobby"
    assert row["building_id"] == 1


def test_common_area_requires_a_valid_building_and_name():
    with pytest.raises(ValueError):
        create_ticket(1, None, "COMMON_AREA", "", "Lift is broken", common_building_id=1)
    with pytest.raises(ValueError):
        create_ticket(1, None, "COMMON_AREA", "Lift lobby", "Lift is broken", common_building_id=999)


def test_tenant_ticket_list_is_scoped_to_tenant():
    create_ticket(1, 1, "UNIT", None, "Tap leaking")
    assert all(row["tenant_id"] == 1 for row in get_tenant_tickets(1))
    assert len(get_tenant_tickets(2)) == 0


def test_audit_history_records_submission_and_landlord_actions():
    ticket_id, _ = create_ticket(1, 1, "UNIT", None, "Tap leaking")
    update_ticket(ticket_id, 1, 1, "ACKNOWLEDGED")
    events = get_ticket_events(ticket_id, landlord_id=1)
    assert [event["to_status"] for event in events] == ["OPEN", "ACKNOWLEDGED"]
    assert events[0]["actor_role"] == "TENANT"
    assert events[1]["actor_role"] == "LANDLORD"


def test_tenant_and_landlord_cannot_view_another_partys_audit_history():
    ticket_id, _ = create_ticket(1, 1, "UNIT", None, "Tap leaking")
    with pytest.raises(PermissionError):
        get_ticket_events(ticket_id, tenant_id=2)
    with pytest.raises(PermissionError):
        get_ticket_events(ticket_id, landlord_id=2)


def test_tenant_can_reopen_after_resolution():
    ticket_id, _ = create_ticket(1, 1, "UNIT", None, "Tap leaking")
    update_ticket(ticket_id, 1, 1, "ACKNOWLEDGED")
    update_ticket(ticket_id, 1, 1, "IN_PROGRESS")
    update_ticket(ticket_id, 1, 1, "RESOLVED", "Replaced washer")
    tenant_confirm(ticket_id, 1, False, "The leak is still present")
    with connect() as conn:
        status = conn.execute(
            "SELECT status FROM maintenance_tickets WHERE ticket_id=?", (ticket_id,)
        ).fetchone()["status"]
    assert status == "REOPENED"


def test_landlord_requires_reason_for_reject_and_on_hold():
    reject_id, _ = create_ticket(1, 1, "UNIT", None, "Broken door")
    with pytest.raises(ValueError):
        update_ticket(reject_id, 1, 1, "REJECTED", "")
    update_ticket(reject_id, 1, 1, "REJECTED", "Not a landlord responsibility")

    hold_id, _ = create_ticket(1, 1, "UNIT", None, "Tap leaking")
    with pytest.raises(ValueError):
        update_ticket(hold_id, 1, 1, "ON_HOLD", "")
    update_ticket(hold_id, 1, 1, "ON_HOLD", "Waiting for spare part")


def test_duplicate_detection_flags_similar_same_building_request():
    first_id, _ = create_ticket(
        1, 1, "UNIT", None, "Bathroom pipe leaking near the sink"
    )
    second_id, _ = create_ticket(
        1, 1, "UNIT", None, "Bathroom pipe leaking near the sink again"
    )
    matches = find_possible_duplicates(second_id, 1)
    assert any(item["ticket_id"] == first_id for item in matches)
    assert all("ticket_id" in item and "similarity" in item for item in matches)


def test_duplicate_detection_does_not_merge_or_delete_tickets():
    first_id, _ = create_ticket(1, 1, "UNIT", None, "Bathroom pipe leaking")
    second_id, _ = create_ticket(1, 1, "UNIT", None, "Bathroom pipe leaking again")
    find_possible_duplicates(second_id, 1)
    with connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM maintenance_tickets WHERE ticket_id IN (?,?)",
            (first_id, second_id)
        ).fetchone()[0]
    assert count == 2


def test_duplicate_detection_is_restricted_to_landlords_own_tickets():
    ticket_id, _ = create_ticket(1, 1, "UNIT", None, "Bathroom pipe leaking")
    with pytest.raises(PermissionError):
        find_possible_duplicates(ticket_id, 2)
