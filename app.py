import streamlit as st
from Maintenance.backend.database import init_db, connect
from Maintenance.backend.services import (tenant_options, create_ticket, get_tenant_tickets, get_landlord_tickets,
                     update_ticket, tenant_confirm, get_ticket_events, get_ticket_attachments,
                     find_possible_duplicates)

st.set_page_config(page_title="TenantEase Maintenance", page_icon="🏠", layout="wide")
init_db()
st.title("🏠 TenantEase | Maintenance Desk")
st.caption("AI-assisted maintenance management · Demo data · Simulated login")

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_TOTAL_BYTES = 40 * 1024 * 1024


def render_attachments(ticket_id: int, tenant_id: int | None = None, landlord_id: int | None = None):
    attachments = get_ticket_attachments(ticket_id, tenant_id=tenant_id, landlord_id=landlord_id)
    if not attachments:
        return
    st.markdown("**Attachments**")
    cols = st.columns(min(3, len(attachments)))
    for index, item in enumerate(attachments):
        with cols[index % len(cols)]:
            st.caption(item["filename"])
            if item["media_type"] == "image":
                st.image(item["data"], use_container_width=True)
            else:
                st.video(item["data"])


def build_attachment_records(uploaded_files):
    records = []
    total = 0
    for uploaded in uploaded_files or []:
        data = uploaded.getvalue()
        total += len(data)
        if len(data) > MAX_FILE_BYTES:
            raise ValueError(f"{uploaded.name} is larger than 20 MB. Please choose a smaller file.")
        if uploaded.type.startswith("image/"):
            media_type = "image"
        elif uploaded.type.startswith("video/"):
            media_type = "video"
        else:
            raise ValueError(f"{uploaded.name}: only image and video files are supported.")
        records.append({"filename": uploaded.name, "mime_type": uploaded.type,
                        "media_type": media_type, "data": data})
    if total > MAX_TOTAL_BYTES:
        raise ValueError("Combined attachments must be 40 MB or less per ticket.")
    return records


with st.sidebar:
    st.header("Demo login")
    role = st.radio("Continue as", ["Tenant", "Landlord"])
    with connect() as conn:
        if role == "Tenant":
            people = conn.execute("SELECT tenant_id AS id, name FROM tenants ORDER BY name").fetchall()
        else:
            people = conn.execute("SELECT landlord_id AS id, name FROM landlords ORDER BY name").fetchall()
    person_map = {p["name"]: p["id"] for p in people}
    selected_name = st.selectbox("Choose demo account", list(person_map))
    actor_id = person_map[selected_name]
    st.info("This account switcher simulates authentication. Do not use it as production login.")

if role == "Tenant":
    st.subheader(f"Welcome, {selected_name}")
    st.write("Report a repair issue and follow its progress. Your identity and property details are attached by the system.")
    options = tenant_options(actor_id)
    if not options:
        st.warning("No active lease is linked to this demo tenant.")
    else:
        # Keep the location selector outside the form so changing it immediately
        # reruns the page and displays only the controls for that location type.
        area_type = st.radio(
            "Where is the issue?",
            ["UNIT", "COMMON_AREA"],
            format_func=lambda x: "Inside my unit" if x == "UNIT" else "Common area",
            horizontal=True,
            key="tenant_request_area_type",
        )

        chosen = None
        common_area = None
        common_building_id = None
        option_labels = [f"{o['building_name']} · {o['unit_label']}" for o in options]

        with st.form("new_ticket", clear_on_submit=True):
            if area_type == "UNIT":
                selected = st.selectbox(
                    "Select the affected unit",
                    range(len(options)),
                    format_func=lambda i: option_labels[i],
                    key="tenant_request_unit",
                )
                chosen = options[selected]["unit_id"]
            else:
                buildings = sorted({(o['building_id'], o['building_name']) for o in options}, key=lambda x: x[1])
                if len(buildings) > 1:
                    selected_building = st.selectbox(
                        "Choose the affected building",
                        buildings,
                        format_func=lambda x: x[1],
                        key="tenant_request_common_building",
                    )
                    common_building_id = selected_building[0]
                elif buildings:
                    common_building_id = buildings[0][0]
                common_area = st.selectbox(
                    "Choose common area",
                    ["Lift / Elevator", "Staircase", "Parking", "Lobby", "Terrace", "Other"],
                    key="tenant_request_common_area",
                )
            title = st.text_input("Issue title", placeholder="e.g. Bathroom pipe leaking")
            description = st.text_area("Describe the problem", placeholder="Example: Bathroom tap is leaking and water is collecting on the floor.", height=110)
            uploaded_files = st.file_uploader(
                "Add photos or a short video (optional)",
                type=["jpg", "jpeg", "png", "webp", "mp4", "mov", "webm"],
                accept_multiple_files=True,
                help="Images and videos up to 20 MB each; 40 MB combined per ticket.",
            )
            submitted = st.form_submit_button("Submit maintenance request", type="primary")
            if submitted:
                try:
                    attachments = build_attachment_records(uploaded_files)
                    ticket_id, triage = create_ticket(actor_id, chosen, area_type, common_area, description,
                                                      common_building_id, title=title or "Maintenance request",
                                                      attachments=attachments)
                    if triage.get("jev_response"):
                        with st.expander("Raw JEV response", expanded=True):
                            st.json(triage["jev_response"])
                    source_label = "JEV AI" if triage["classification_source"] == "JEV" else "rule-based fallback"
                    st.session_state["tenant_request_confirmation"] = {
                        "ticket_id": ticket_id,
                        "category": triage["category"],
                        "urgency": triage["urgency"],
                        "source": source_label,
                    }
                    if triage["safety"]:
                        st.error("Safety warning: this request was automatically marked URGENT. Contact emergency services / the relevant utility immediately if anyone is in danger; do not wait for an app response.")
                    if triage["jev_error"]:
                        st.warning("JEV was unavailable or its response could not be interpreted. A transparent rule-based fallback was used. Check JEV settings and the diagnostic message in the ticket record.")
                    
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

        # Show confirmation after rerun, outside the form so it remains visible.
        confirmation = st.session_state.pop("tenant_request_confirmation", None)
        if confirmation:
            st.success(
                f"✓ Maintenance request #{confirmation['ticket_id']} has been sent successfully. "
                f"Category: {confirmation['category']} · Priority: {confirmation['urgency']}. "
                f"You can track its progress under My maintenance requests."
            )
    st.divider()
    st.subheader("My maintenance requests")
    tickets = get_tenant_tickets(actor_id)
    if not tickets:
        st.info("You have not submitted any maintenance requests yet.")
    for t in tickets:
        label = f"#{t['ticket_id']} · {t['category']} · {t['status']} · {t['building_name']} · {t['unit_label'] or t['common_area_name'] or 'Common area'}"
        with st.expander(label):
            st.write(f"**{t['title']}**")
            st.write(t["description"])
            st.write(f"**Priority:** {t['urgency']}  |  **Suggested service:** {t['suggested_vendor_type']}")
            st.caption(f"Classification: {t['classification_source']}")
            render_attachments(t["ticket_id"], tenant_id=actor_id)
            if t["safety_flag"]:
                st.error("Safety flag raised")
            if t["jev_error"]:
                with st.expander("AI classification diagnostic"):
                    st.code(t["jev_error"])
            if t["resolution_note"]:
                st.info(f"Landlord's work note: {t['resolution_note']}")
            if t["status"] == "RESOLVED":
                c1, c2 = st.columns(2)
                if c1.button("Confirm repair", key=f"confirm_{t['ticket_id']}"):
                    tenant_confirm(t["ticket_id"], actor_id, True)
                    st.rerun()
                if c2.button("Not fixed — reopen", key=f"reopen_{t['ticket_id']}"):
                    tenant_confirm(t["ticket_id"], actor_id, False)
                    st.rerun()
            with st.expander("Status history"):
                for e in get_ticket_events(t["ticket_id"], tenant_id=actor_id):
                    st.caption(f"{e['created_at']} · {e['actor_role']} · {e['from_status'] or '—'} → {e['to_status']} · {e['note'] or ''}")


else:
    st.subheader(f"Landlord workspace · {selected_name}")

    # Show the last successful action after Streamlit reruns the page.
    flash_message = st.session_state.pop("ticket_action_flash", None)
    if flash_message:
        st.success(f"✓ {flash_message}")

    LANDLORD_ACTIONS = {
        "OPEN": {
            "Acknowledge request": "ACKNOWLEDGED",
            "Reject complaint": "REJECTED",
            "Put on hold": "ON_HOLD",
        },
        "REOPENED": {
            "Acknowledge request": "ACKNOWLEDGED",
            "Reject complaint": "REJECTED",
            "Put on hold": "ON_HOLD",
        },
        "ACKNOWLEDGED": {
            "Start work": "IN_PROGRESS",
            "Reject complaint": "REJECTED",
            "Put on hold": "ON_HOLD",
        },
        "IN_PROGRESS": {
            "Mark resolved": "RESOLVED",
            "Put on hold": "ON_HOLD",
        },
        "ON_HOLD": {
            "Resume / acknowledge": "ACKNOWLEDGED",
            "Resume work": "IN_PROGRESS",
            "Reject complaint": "REJECTED",
        },
    }

    statuses = [
        "ALL",
        "OPEN",
        "ACKNOWLEDGED",
        "IN_PROGRESS",
        "ON_HOLD",
        "REOPENED",
        "RESOLVED",
        "REJECTED",
        "CLOSED",
    ]

    # Load all complaints first so dashboard metrics are not distorted by filters.
    all_tickets = get_landlord_tickets(actor_id, "ALL")
    active_statuses = {"OPEN", "ACKNOWLEDGED", "IN_PROGRESS", "ON_HOLD", "REOPENED"}

    from datetime import datetime, timedelta

    def ticket_age_days(value):
        try:
            created = datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
            return (datetime.now() - created).days
        except (TypeError, ValueError):
            return 0

    overdue_days = st.slider("Mark requests overdue after (days)", 1, 30, 7)
    overdue_tickets = [
        t for t in all_tickets
        if t["status"] in active_statuses and ticket_age_days(t["created_at"]) >= overdue_days
    ]

    total_open = sum(1 for t in all_tickets if t["status"] in active_statuses)
    urgent_open = sum(1 for t in all_tickets if t["status"] in active_statuses and t["urgency"] == "URGENT")
    resolved_total = sum(1 for t in all_tickets if t["status"] in {"RESOLVED", "CLOSED"})

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Open requests", total_open)
    m2.metric("Urgent open", urgent_open)
    m3.metric("Overdue requests", len(overdue_tickets))
    m4.metric("Resolved / closed", resolved_total)

    st.markdown("#### Maintenance overview")
    if overdue_tickets:
        oldest = max(overdue_tickets, key=lambda t: ticket_age_days(t["created_at"]))
        st.warning(
            f"{len(overdue_tickets)} request(s) have been open for at least "
            f"{overdue_days} days. Oldest: #{oldest['ticket_id']} — "
            f"{oldest['title']} ({ticket_age_days(oldest['created_at'])} days)."
        )
    else:
        st.success(f"No open requests are overdue by the {overdue_days}-day threshold.")

    with st.expander("Category overview"):
        category_counts = {}
        for item in all_tickets:
            category_counts[item["category"]] = category_counts.get(item["category"], 0) + 1
        if category_counts:
            st.bar_chart(category_counts)
        else:
            st.caption("No maintenance requests yet.")

    st.markdown("#### Filter maintenance requests")

    # Normalize values before comparing them. This avoids missed matches caused
    # by NULL values, extra spaces, or inconsistent capitalization in SQLite.
    def filter_value(value):
        return str(value or "").strip().casefold()

    building_options = ["ALL"] + sorted(
        {str(t["building_name"] or "Unknown property").strip() for t in all_tickets},
        key=str.casefold,
    )
    category_options = ["ALL"] + sorted(
        {str(t["category"] or "Unclassified").strip() for t in all_tickets},
        key=str.casefold,
    )
    urgency_options = ["ALL", "URGENT", "HIGH", "NORMAL", "LOW"]

    f1, f2, f3, f4 = st.columns(4)
    with f1:
        selected_building = st.selectbox(
            "Property", building_options, key="landlord_filter_property"
        )
    with f2:
        selected_category = st.selectbox(
            "Category", category_options, key="landlord_filter_category"
        )
    with f3:
        selected_urgency = st.selectbox(
            "Urgency", urgency_options, key="landlord_filter_urgency"
        )
    with f4:
        selected_status = st.selectbox(
            "Status", statuses, key="landlord_filter_status"
        )

    overdue_only = st.checkbox(
        "Show overdue requests only", key="landlord_filter_overdue_only"
    )

    # Apply each selected filter independently. Multiple selected filters are
    # combined, so the results must satisfy every non-ALL selection.
    tickets = []
    for ticket in all_tickets:
        property_name = ticket["building_name"] or "Unknown property"
        category_name = ticket["category"] or "Unclassified"

        if selected_building != "ALL" and filter_value(property_name) != filter_value(selected_building):
            continue
        if selected_category != "ALL" and filter_value(category_name) != filter_value(selected_category):
            continue
        if selected_urgency != "ALL" and filter_value(ticket["urgency"]) != filter_value(selected_urgency):
            continue
        if selected_status != "ALL" and filter_value(ticket["status"]) != filter_value(selected_status):
            continue
        if overdue_only and not (
            ticket["status"] in active_statuses
            and ticket_age_days(ticket["created_at"]) >= overdue_days
        ):
            continue

        tickets.append(ticket)

    st.caption(f"Showing {len(tickets)} of {len(all_tickets)} maintenance request(s).")
    if not tickets:
        st.info("No maintenance requests match these filters.")

    for t in tickets:

        where = (
            t["unit_label"]
            or t["common_area_name"]
            or "Common area"
        )

        label = (
            f"#{t['ticket_id']} · {t['urgency']} · "
            f"{t['category']} · {t['building_name']} / "
            f"{where} · {t['status']}"
        )

        with st.expander(
            label,
            expanded=t["urgency"] == "URGENT"
        ):

            st.write(
                f"**Tenant:** {t['tenant_name']} · {t['tenant_phone']}"
            )

            st.write(
                f"**Issue:** {t['title']} — {t['description']}"
            )

            possible_duplicates = find_possible_duplicates(t["ticket_id"], actor_id)
            if possible_duplicates:
                st.warning("Possible duplicate or related maintenance complaint(s) found. Please compare before taking action.")
                for duplicate in possible_duplicates:
                    location_text = "Same location" if duplicate["same_location"] else "Possibly related location"
                    st.caption(
                        f"#{duplicate['ticket_id']} · {duplicate['title']} · "
                        f"{duplicate['category']} · {duplicate['status']} · "
                        f"{location_text} · {duplicate['similarity']}% text similarity"
                    )
                    st.write(duplicate["description"])

            st.write(
                f"**Suggested vendor:** {t['suggested_vendor_type']}"
            )

            st.caption(
                f"AI classification source: {t['classification_source']}"
            )

            render_attachments(
                t["ticket_id"],
                landlord_id=actor_id
            )

            if t["safety_flag"]:
                st.error(
                    "SAFETY FLAG — urgent human attention required"
                )

            if t["jev_error"]:
                with st.expander("AI classification diagnostic"):
                    st.code(t["jev_error"])

            if t["resolution_note"]:
                st.info(
                    f"Resolution note: {t['resolution_note']}"
                )

            st.caption(
                f"Submitted: {t['created_at']} · "
                f"Updated: {t['updated_at']}"
            )

            # Show the actions available for this complaint.
            actions = LANDLORD_ACTIONS.get(t["status"], {})

            if actions:

                action_labels = list(actions.keys())

                with st.form(f"landlord_action_{t['ticket_id']}"):

                    st.markdown("**Manage this complaint**")

                    selected_action = st.selectbox(
                        "Choose an action",
                        action_labels,
                        # Reset to a valid choice whenever this ticket's status changes.
                        key=f"action_{t['ticket_id']}_{t['status']}"
                    )

                    selected_status_value = actions[selected_action]

                    if selected_status_value == "RESOLVED":
                        note_label = "Work completed details"
                        placeholder = (
                            "Describe the repair completed and "
                            "any parts replaced."
                        )
                    elif selected_status_value == "REJECTED":
                        note_label = "Reason for rejection"
                        placeholder = (
                            "Explain why this complaint cannot be handled."
                        )
                    elif selected_status_value == "ON_HOLD":
                        note_label = "Reason for putting on hold"
                        placeholder = (
                            "Explain why work is delayed and, if known, "
                            "when it may resume."
                        )
                    else:
                        note_label = "Additional note (optional)"
                        placeholder = (
                            "Add an update for the tenant, if needed."
                        )

                    note = st.text_area(
                        note_label,
                        placeholder=placeholder,
                        key=f"note_{t['ticket_id']}"
                    )

                    submitted = st.form_submit_button(
                        "Submit action",
                        type="primary"
                    )

                    if submitted:
                        try:
                            update_ticket(
                                t["ticket_id"],
                                actor_id,
                                actor_id,
                                selected_status_value,
                                note
                            )

                            # Preserve the confirmation across Streamlit's rerun.
                            st.session_state["ticket_action_flash"] = (
                                f"Complaint #{t['ticket_id']} status changed "
                                f"from {t['status']} to {selected_status_value}."
                            )
                            st.rerun()

                        except Exception as exc:
                            st.error(str(exc))

            elif t["status"] == "RESOLVED":
                st.info(
                    "Waiting for the tenant to confirm the repair "
                    "or reopen the complaint."
                )

            elif t["status"] == "REJECTED":
                st.error(
                    "This complaint has been rejected. "
                    "The reason is available in the audit history."
                )

            elif t["status"] == "CLOSED":
                st.success("Tenant confirmed the repair.")

            # Complete history of landlord and tenant actions.
            with st.expander("Audit history"):

                events = get_ticket_events(
                    t["ticket_id"],
                    landlord_id=actor_id
                )

                for e in events:
                    st.caption(
                        f"{e['created_at']} · "
                        f"{e['actor_role']} · "
                        f"{e['from_status'] or '—'} → "
                        f"{e['to_status']} · "
                        f"{e['note'] or ''}"
                    )


st.divider()
st.caption("PoC: JEV-assisted category and priority classification with deterministic safety overrides; rule-based fallback if JEV is not configured. Demo login only. Attachments are stored in SQLite for this local prototype.")
