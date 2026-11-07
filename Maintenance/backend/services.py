"""Business rules and JEV-assisted maintenance triage.

Tenant/property identity is always resolved from SQLite, never from submitted text or AI output.
"""
from __future__ import annotations

import json
import os
import re
from difflib import SequenceMatcher
from typing import Any

import httpx
from dotenv import load_dotenv
from Maintenance.backend.database import connect

load_dotenv()

MAINTENANCE_CATEGORIES = {
    "Plumbing": "Leaks, taps, pipes, drainage, toilets, water supply, geysers and water heaters.",
    "Electrical": "Wiring, switches, sockets, lights, power failures, short circuits and electrical faults.",
    "Civil / Structural": "Walls, ceilings, floors, cracks, seepage, doors, windows and structural damage.",
    "Appliance Repair": "Refrigerators, air conditioners, washing machines, fans and other supplied appliances.",
    "Cleaning": "Cleaning, garbage collection, sanitation and housekeeping issues.",
    "Pest Control": "Cockroaches, termites, rodents, mosquitoes and other pest infestations.",
    "Lift / Elevator": "Lift or elevator breakdowns, doors, controls and safety issues.",
    "Water Supply": "No water, low water pressure, water tank and supply interruptions.",
    "Other": "Maintenance requests that do not fit another category.",
}

SAFETY_TERMS = [
    "gas smell", "smell gas", "smell of gas", "gas leak", "sparking", "electric shock",
    "fire", "flooding", "ceiling collapsing", "ceiling is collapsing",
    "exposed wire", "burning smell",
]

VENDOR_BY_CATEGORY = {
    "Plumbing": "Plumber",
    "Electrical": "Licensed electrician",
    "Civil / Structural": "Civil contractor / mason",
    "Appliance Repair": "Appliance technician",
    "Cleaning": "Cleaning service",
    "Pest Control": "Pest-control service",
    "Lift / Elevator": "Authorized lift technician",
    "Water Supply": "Plumber / water-system technician",
    "Other": "General maintenance technician",
}


def _rule_triage(description: str) -> dict:
    text = description.lower()
    safety = any(term in text for term in SAFETY_TERMS)
    if any(w in text for w in ["lift", "elevator"]):
        category = "Lift / Elevator"
    elif any(w in text for w in ["geyser", "fridge", "refrigerator", "washing machine", "ac not", "air conditioner"]):
        category = "Appliance Repair"
    elif any(w in text for w in ["cockroach", "termite", "rat", "rodent", "mosquito", "pest"]):
        category = "Pest Control"
    elif any(w in text for w in ["clean", "garbage", "dustbin", "sanitation"]):
        category = "Cleaning"
    elif any(w in text for w in ["crack", "wall", "ceiling", "floor tile", "seepage", "plaster", "door", "window"]):
        category = "Civil / Structural"
    elif any(w in text for w in ["no water", "water supply", "water pressure", "tank"]):
        category = "Water Supply"
    elif any(w in text for w in ["switch", "wire", "electric", "spark", "light", "power", "socket"]):
        category = "Electrical"
    elif any(w in text for w in ["leak", "pipe", "tap", "drain", "water", "paani", "toilet"]):
        category = "Plumbing"
    else:
        category = "Other"
    urgency = "URGENT" if safety else (
        "HIGH" if any(w in text for w in ["urgent", "asap", "immediately", "overflow", "blocked completely"]) else "NORMAL"
    )
    return {
        "category": category,
        "vendor": VENDOR_BY_CATEGORY[category],
        "safety": safety,
        "urgency": urgency,
        "summary": " ".join(description.strip().split())[:160],
        "classification_source": "RULES_FALLBACK",
        "jev_response": None,
        "jev_error": None,
    }

def _normalise_category(value: Any) -> str | None:
    if value is None:
        return None

    candidate = str(value).strip()

    for category in MAINTENANCE_CATEGORIES:
        if candidate.casefold() == category.casefold():
            return category

    for category in MAINTENANCE_CATEGORIES:
        if category.casefold() in candidate.casefold():
            return category

    return None

def _normalise_urgency(value: Any) -> str | None:
    """Convert JEV priority labels into application urgency labels."""

    if value is None:
        return None

    mapping = {
        "low": "LOW",
        "normal": "NORMAL",
        "urgent": "URGENT",
    }

    return mapping.get(str(value).strip().lower())





def jev_categorization(
    description: str,
    title: str = "Maintenance request"
) -> dict:
    """Call JEV and parse its established response format."""

    base_url = os.getenv("JEV_BASE_URL", "").strip()
    api_key = os.getenv("JEV_API_KEY", "").strip()

    if not base_url or not api_key:
        raise RuntimeError(
            "JEV is not configured. Set JEV_BASE_URL and JEV_API_KEY in your .env file."
        )

    payload = {
        "model": "jev-latest",
        "state": {
            "subject": title.strip() or "Maintenance request",
            "body": description.strip(),
        },
        "questions": {
            "categories": {
                "type": "choice",
                "instructions": (
                    "Which maintenance category best fits the tenant's "
                    "reported issue? Choose exactly one category."
                ),
                "criteria": MAINTENANCE_CATEGORIES,
            },
            "priority": {
                "type": "score",
                "instructions": (
                    "What priority should this maintenance request "
                    "receive based on urgency and potential impact?"
                ),
                "criteria": ["low", "normal", "urgent"],
            },
        },
    }

    response = httpx.post(
        url=base_url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=httpx.Timeout(25.0, connect=10.0),
    )

    response.raise_for_status()

    raw = response.json()
    answers = raw.get("answers", {})

    # 1. Read category from JEV's choice field.
    category_answer = answers.get("categories", {})

    if not isinstance(category_answer, dict):
        raise ValueError("JEV categories response is not in the expected format.")

    category = _normalise_category(
        category_answer.get("choice")
    )

    category_confidence = category_answer.get("confidence")

    # 2. Read priority from JEV's probabilities and legend.
    priority_answer = answers.get("priority", {})

    if not isinstance(priority_answer, dict):
        raise ValueError("JEV priority response is not in the expected format.")

    probabilities = priority_answer.get("probabilities", {})
    legend = priority_answer.get("legend", {})

    if not isinstance(probabilities, dict) or not probabilities:
        raise ValueError("JEV priority probabilities are missing.")

    if not isinstance(legend, dict) or not legend:
        raise ValueError("JEV priority legend is missing.")

    # Find the priority key with the highest probability.
    best_priority_key = max(
        probabilities,
        key=lambda key: float(probabilities[key])
    )

    # Translate the key using JEV's legend.
    priority_label = legend.get(str(best_priority_key))

    urgency = _normalise_urgency(priority_label)

    priority_score = priority_answer.get("score")
    priority_confidence = priority_answer.get("confidence")

    # 3. Independently check safety terms.
    description_lower = description.lower()

    safety = any(
        term in description_lower
        for term in SAFETY_TERMS
    )

    # 4. Safety issues always override JEV's priority.
    if safety:
        urgency = "URGENT"

    # 5. Validate the JEV response.
    if not category or not urgency:
        raise ValueError(
            "JEV response could not be parsed. "
            "Check the category choice and priority legend."
        )

    return {
        "category": category,
        "vendor": VENDOR_BY_CATEGORY.get(
            category,
            VENDOR_BY_CATEGORY["Other"]
        ),
        "safety": safety,
        "urgency": urgency,
        "summary": " ".join(description.strip().split())[:160],
        "classification_source": "JEV",
        "jev_response": raw,
        "jev_error": None,
        "category_confidence": category_confidence,
        "priority_score": priority_score,
        "priority_confidence": priority_confidence,
    }



def triage(description: str, title: str = "Maintenance request") -> dict:
    """Prefer JEV; use transparent keyword fallback if JEV is not configured/unavailable."""
    try:
        return jev_categorization(description, title)
    except Exception as exc:
        result = _rule_triage(description)
        result["jev_error"] = f"{type(exc).__name__}: {exc}"
        # Even in fallback mode, enforce the emergency override.
        if result["safety"]:
            result["urgency"] = "URGENT"
        return result


def tenant_options(tenant_id: int):
    with connect() as conn:
        return conn.execute("""
            SELECT l.lease_id, u.unit_id, u.unit_label, b.building_id, b.name AS building_name,
                   b.address, b.landlord_id
            FROM leases l JOIN units u ON u.unit_id=l.unit_id
            JOIN buildings b ON b.building_id=u.building_id
            WHERE l.tenant_id=? AND l.active=1
            ORDER BY b.name, u.unit_label
        """, (tenant_id,)).fetchall()


def create_ticket(tenant_id: int, unit_id: int | None, area_type: str, common_area: str | None,
                  description: str, common_building_id: int | None = None, title: str = "Maintenance request",
                  attachments: list[dict] | None = None):
    if not description.strip():
        raise ValueError("Please describe the maintenance issue.")
    # Resolve tenant/property ownership before making an external AI request.
    with connect() as conn:
        if area_type == "UNIT":
            row = conn.execute("""
                SELECT u.unit_id, b.building_id, b.landlord_id
                FROM leases l JOIN units u ON u.unit_id=l.unit_id
                JOIN buildings b ON b.building_id=u.building_id
                WHERE l.tenant_id=? AND l.unit_id=? AND l.active=1
            """, (tenant_id, unit_id)).fetchone()
            if not row:
                raise PermissionError("That unit is not linked to your active lease.")
            resolved_unit, building_id, landlord_id = row["unit_id"], row["building_id"], row["landlord_id"]
        else:
            if not common_area or not common_area.strip():
                raise ValueError("Choose the common area.")
            rows = conn.execute("""
                SELECT DISTINCT b.building_id, b.landlord_id, b.name FROM leases l
                JOIN units u ON u.unit_id=l.unit_id JOIN buildings b ON b.building_id=u.building_id
                WHERE l.tenant_id=? AND l.active=1
            """, (tenant_id,)).fetchall()
            selected_building = next((r for r in rows if r["building_id"] == common_building_id), None) if common_building_id else (rows[0] if len(rows) == 1 else None)
            if not selected_building:
                raise ValueError("Choose a building linked to one of your active leases for this common-area request.")
            resolved_unit, building_id, landlord_id = None, selected_building["building_id"], selected_building["landlord_id"]

        # AI is only allowed to classify the description; it cannot set ownership metadata.
        result = triage(description, title)
        cur = conn.execute("""
            INSERT INTO maintenance_tickets
            (tenant_id,unit_id,building_id,landlord_id,area_type,common_area_name,title,description,category,urgency,
             safety_flag,summary,suggested_vendor_type,classification_source,jev_response,jev_error)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (tenant_id, resolved_unit, building_id, landlord_id, area_type,
              common_area.strip() if area_type == "COMMON_AREA" else None, title.strip() or "Maintenance request", description.strip(),
              result["category"], result["urgency"], int(result["safety"]), result["summary"], result["vendor"],
              result["classification_source"], json.dumps(result["jev_response"], ensure_ascii=False) if result["jev_response"] is not None else None,
              result["jev_error"]))
        ticket_id = cur.lastrowid
        for attachment in attachments or []:
            conn.execute("""
                INSERT INTO ticket_attachments(ticket_id,uploaded_by_role,uploaded_by_id,filename,mime_type,media_type,data)
                VALUES (?,?,?,?,?,?,?)
            """, (ticket_id, "TENANT", tenant_id, attachment["filename"], attachment["mime_type"],
                  attachment["media_type"], attachment["data"]))
        conn.execute("INSERT INTO ticket_events(ticket_id,actor_role,actor_id,from_status,to_status,note) VALUES (?,?,?,?,?,?)",
                     (ticket_id, "TENANT", tenant_id, None, "OPEN", "Ticket submitted"))
        conn.commit()
        return ticket_id, result


def get_ticket_attachments(ticket_id: int, tenant_id: int | None = None, landlord_id: int | None = None):
    with connect() as conn:
        if tenant_id is not None:
            allowed = conn.execute("SELECT 1 FROM maintenance_tickets WHERE ticket_id=? AND tenant_id=?", (ticket_id, tenant_id)).fetchone()
        else:
            allowed = conn.execute("SELECT 1 FROM maintenance_tickets WHERE ticket_id=? AND landlord_id=?", (ticket_id, landlord_id)).fetchone()
        if not allowed:
            raise PermissionError("You cannot view this ticket's attachments.")
        return conn.execute("SELECT attachment_id,filename,mime_type,media_type,data FROM ticket_attachments WHERE ticket_id=? ORDER BY attachment_id", (ticket_id,)).fetchall()


def get_tenant_tickets(tenant_id: int):
    with connect() as conn:
        return conn.execute("""
            SELECT t.*, u.unit_label, b.name AS building_name
            FROM maintenance_tickets t JOIN buildings b ON b.building_id=t.building_id
            LEFT JOIN units u ON u.unit_id=t.unit_id
            WHERE t.tenant_id=? ORDER BY t.created_at DESC, t.ticket_id DESC
        """, (tenant_id,)).fetchall()


def get_landlord_tickets(landlord_id: int, status: str = "ALL"):
    with connect() as conn:
        query = """
            SELECT t.*, te.name AS tenant_name, te.phone AS tenant_phone,
                   u.unit_label, b.name AS building_name
            FROM maintenance_tickets t JOIN tenants te ON te.tenant_id=t.tenant_id
            JOIN buildings b ON b.building_id=t.building_id LEFT JOIN units u ON u.unit_id=t.unit_id
            WHERE t.landlord_id=?
        """
        params = [landlord_id]
        if status != "ALL":
            query += " AND t.status=?"
            params.append(status)
        query += " ORDER BY CASE t.urgency WHEN 'URGENT' THEN 0 WHEN 'HIGH' THEN 1 WHEN 'NORMAL' THEN 2 ELSE 3 END, t.created_at DESC"
        return conn.execute(query, params).fetchall()



def update_ticket(
    ticket_id: int,
    landlord_id: int,
    actor_id: int,
    new_status: str,
    note: str = ""
):
    """Update a maintenance ticket using permitted landlord actions."""

    allowed = {
        "OPEN": {
            "ACKNOWLEDGED",
            "REJECTED",
            "ON_HOLD",
        },
        "REOPENED": {
            "ACKNOWLEDGED",
            "REJECTED",
            "ON_HOLD",
        },
        "ACKNOWLEDGED": {
            "IN_PROGRESS",
            "REJECTED",
            "ON_HOLD",
        },
        "IN_PROGRESS": {
            "RESOLVED",
            "ON_HOLD",
        },
        "ON_HOLD": {
            "ACKNOWLEDGED",
            "IN_PROGRESS",
            "REJECTED",
        },
    }

    new_status = new_status.strip().upper()
    note = note.strip()

    with connect() as conn:

        ticket = conn.execute(
            """
            SELECT *
            FROM maintenance_tickets
            WHERE ticket_id=? AND landlord_id=?
            """,
            (ticket_id, landlord_id)
        ).fetchone()

        if not ticket:
            raise PermissionError(
                "Ticket not found for this landlord."
            )

        current_status = ticket["status"]

        # Validate the requested status transition.
        if new_status not in allowed.get(current_status, set()):
            raise ValueError(
                f"Cannot move ticket from {current_status} "
                f"to {new_status}."
            )

        # Reasons are compulsory for these actions.
        if new_status in {"REJECTED", "ON_HOLD", "RESOLVED"}:
            if not note:
                if new_status == "REJECTED":
                    raise ValueError(
                        "Provide a reason for rejecting this complaint."
                    )

                if new_status == "ON_HOLD":
                    raise ValueError(
                        "Provide a reason for putting this complaint on hold."
                    )

                if new_status == "RESOLVED":
                    raise ValueError(
                        "Add a work-completed note before resolving."
                    )

        # Update ticket status and resolution note.
        conn.execute(
            """
            UPDATE maintenance_tickets
            SET status=?,
                resolution_note=CASE
                    WHEN ?='RESOLVED' THEN ?
                    ELSE resolution_note
                END,
                updated_at=datetime('now')
            WHERE ticket_id=?
            """,
            (
                new_status,
                new_status,
                note,
                ticket_id
            )
        )

        # Record every landlord action in the ticket history.
        conn.execute(
            """
            INSERT INTO ticket_events
            (
                ticket_id,
                actor_role,
                actor_id,
                from_status,
                to_status,
                note
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                ticket_id,
                "LANDLORD",
                actor_id,
                current_status,
                new_status,
                note or None
            )
        )

        conn.commit()



def tenant_confirm(ticket_id: int, tenant_id: int, confirmed: bool, note: str = ""):
    new_status = "CLOSED" if confirmed else "REOPENED"
    with connect() as conn:
        ticket = conn.execute("SELECT * FROM maintenance_tickets WHERE ticket_id=? AND tenant_id=?", (ticket_id, tenant_id)).fetchone()
        if not ticket:
            raise PermissionError("Ticket not found for this tenant.")
        if ticket["status"] != "RESOLVED":
            raise ValueError("You can only confirm or reopen a ticket after the landlord marks it resolved.")
        conn.execute("UPDATE maintenance_tickets SET status=?, updated_at=datetime('now') WHERE ticket_id=?", (new_status, ticket_id))
        conn.execute("INSERT INTO ticket_events(ticket_id,actor_role,actor_id,from_status,to_status,note) VALUES (?,?,?,?,?,?)",
                     (ticket_id, "TENANT", tenant_id, "RESOLVED", new_status, note.strip() or ("Tenant confirmed repair" if confirmed else "Tenant says issue is not fixed")))
        conn.commit()


def get_ticket_events(ticket_id: int, tenant_id: int | None = None, landlord_id: int | None = None):
    with connect() as conn:
        if tenant_id is not None:
            allowed = conn.execute("SELECT 1 FROM maintenance_tickets WHERE ticket_id=? AND tenant_id=?", (ticket_id, tenant_id)).fetchone()
        else:
            allowed = conn.execute("SELECT 1 FROM maintenance_tickets WHERE ticket_id=? AND landlord_id=?", (ticket_id, landlord_id)).fetchone()
        if not allowed:
            raise PermissionError("You cannot view this ticket's history.")
        return conn.execute("SELECT * FROM ticket_events WHERE ticket_id=? ORDER BY created_at,event_id", (ticket_id,)).fetchall()


def find_possible_duplicates(ticket_id: int, landlord_id: int, limit: int = 5):
    """Find likely related active complaints for the same building.

    This only flags possible duplicates for landlord review; it never merges
    or deletes maintenance tickets.
    """
    with connect() as conn:
        current = conn.execute(
            """SELECT ticket_id, building_id, unit_id, area_type, common_area_name,
                      title, description, category
               FROM maintenance_tickets
               WHERE ticket_id=? AND landlord_id=?""",
            (ticket_id, landlord_id)
        ).fetchone()
        if not current:
            raise PermissionError("Ticket not found for this landlord.")

        candidates = conn.execute(
            """SELECT ticket_id, unit_id, area_type, common_area_name, title,
                      description, category, status, created_at
               FROM maintenance_tickets
               WHERE landlord_id=? AND building_id=? AND ticket_id<>?
                 AND status NOT IN ('CLOSED','REJECTED')
               ORDER BY created_at DESC""",
            (landlord_id, current["building_id"], ticket_id)
        ).fetchall()

    def clean(value):
        return re.sub(r"[^a-z0-9 ]+", " ", (value or "").lower()).strip()

    current_text = clean(f"{current['title']} {current['description']}")
    current_location = (current["area_type"], current["unit_id"], clean(current["common_area_name"]))
    matches = []
    for candidate in candidates:
        candidate_text = clean(f"{candidate['title']} {candidate['description']}")
        similarity = SequenceMatcher(None, current_text, candidate_text).ratio()
        candidate_location = (
            candidate["area_type"], candidate["unit_id"],
            clean(candidate["common_area_name"])
        )
        same_location = current_location == candidate_location
        same_category = current["category"] == candidate["category"]
        # Conservative threshold: similar wording, or same category and exact location.
        if similarity >= 0.42 or (same_location and same_category):
            matches.append({
                "ticket_id": candidate["ticket_id"],
                "title": candidate["title"],
                "description": candidate["description"],
                "category": candidate["category"],
                "status": candidate["status"],
                "created_at": candidate["created_at"],
                "similarity": round(similarity * 100),
                "same_location": same_location,
            })
    matches.sort(key=lambda item: (item["same_location"], item["similarity"]), reverse=True)
    return matches[:limit]
