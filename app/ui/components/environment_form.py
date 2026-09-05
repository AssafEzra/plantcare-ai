"""Growing conditions — תנאי הגידול (FINAL §18, `PUT /v1/plants/{id}/environment`).

Reported from real use: *"i couldnt add or edit תנאי הגידול"*. The section
rendered whatever was stored, said "עדיין לא הוגדרו תנאי גידול" when nothing was,
and offered no way to change that — the endpoint has existed since PR 11 and no
screen ever called it. The same shape as the thumbnail nothing set and the
confirmation nothing could reach: two correct halves with nothing joining them.

Worse than merely missing: the caption underneath promised that updating the
conditions triggers a review of the care plan. Nothing could update them, and
nothing would have reviewed anything if they had.

Every field is optional. `FINAL §18` says the Care Agent works with partial data,
and it is the environment the *user* can describe — someone who knows their plant
is on a north-facing windowsill should not have to invent a humidity reading to
say so.
"""

from __future__ import annotations

from collections.abc import Callable

import streamlit as st

from app.common.enums import LightDirection, LightLevel, LocationType

UNSET = "—"

LOCATION_LABELS: dict[str, str] = {
    LocationType.INDOOR.value: "בתוך הבית",
    LocationType.OUTDOOR.value: "בחוץ",
    LocationType.BALCONY.value: "מרפסת",
    LocationType.GREENHOUSE.value: "חממה",
}

LIGHT_LABELS: dict[str, str] = {
    LightLevel.LOW.value: "מעט אור",
    LightLevel.MEDIUM.value: "אור בינוני",
    LightLevel.BRIGHT.value: "אור בהיר",
    LightLevel.DIRECT_SUN.value: "שמש ישירה",
}

DIRECTION_LABELS: dict[str, str] = {
    LightDirection.NORTH.value: "צפון",
    LightDirection.SOUTH.value: "דרום",
    LightDirection.EAST.value: "מזרח",
    LightDirection.WEST.value: "מערב",
    LightDirection.UNKNOWN.value: "לא ידוע",
}

FIELD_LABELS: dict[str, str] = {
    "location_type": "מיקום",
    "light_level": "עוצמת אור",
    "light_direction": "כיוון החלון",
    "temperature_c": "טמפרטורה",
    "humidity_percent": "לחות",
    "room": "חדר",
    "notes": "הערות",
}

VALUE_LABELS: dict[str, dict[str, str]] = {
    "location_type": LOCATION_LABELS,
    "light_level": LIGHT_LABELS,
    "light_direction": DIRECTION_LABELS,
}


def describe(field: str, value: object) -> str:
    """The stored value in Hebrew, for the read-only summary."""
    if field in VALUE_LABELS:
        return VALUE_LABELS[field].get(str(value), str(value))
    if field == "temperature_c":
        return f"{value}°C"
    if field == "humidity_percent":
        return f"{value}%"
    return str(value)


def _choice(label: str, labels: dict[str, str], current: object, key: str) -> str | None:
    options = [UNSET, *labels]
    stored = str(current) if current is not None else UNSET
    return_value = st.selectbox(
        label,
        options=options,
        index=options.index(stored) if stored in options else 0,
        format_func=lambda option: UNSET if option == UNSET else labels[option],
        key=key,
    )
    return None if return_value == UNSET else return_value


def environment_form(
    environment: dict | None,
    *,
    on_save: Callable[[dict], None],
    key_prefix: str = "env",
) -> None:
    """Show the conditions and let the user change them.

    `on_save` receives only what the user actually set. A cleared field is sent as
    `null` rather than omitted, because "I no longer know the humidity" is a real
    edit and the endpoint replaces the row.
    """
    current = environment or {}

    with st.form(f"{key_prefix}_form", border=False):
        location = _choice(
            FIELD_LABELS["location_type"],
            LOCATION_LABELS,
            current.get("location_type"),
            f"{key_prefix}_location",
        )
        light = _choice(
            FIELD_LABELS["light_level"],
            LIGHT_LABELS,
            current.get("light_level"),
            f"{key_prefix}_light",
        )
        direction = _choice(
            FIELD_LABELS["light_direction"],
            DIRECTION_LABELS,
            current.get("light_direction"),
            f"{key_prefix}_direction",
        )

        # Left empty rather than defaulted: a temperature nobody typed is not
        # 20°C, and a care plan built on an invented number is worse than one
        # built on an admitted gap.
        temperature = st.number_input(
            FIELD_LABELS["temperature_c"],
            min_value=-50.0,
            max_value=60.0,
            value=current.get("temperature_c"),
            step=1.0,
            placeholder="לא ידוע",
            key=f"{key_prefix}_temperature",
        )
        humidity = st.number_input(
            FIELD_LABELS["humidity_percent"],
            min_value=0.0,
            max_value=100.0,
            value=current.get("humidity_percent"),
            step=5.0,
            placeholder="לא ידוע",
            key=f"{key_prefix}_humidity",
        )
        room = st.text_input(
            FIELD_LABELS["room"],
            value=current.get("room") or "",
            placeholder="למשל: הסלון",
            max_chars=120,
            key=f"{key_prefix}_room",
        )
        notes = st.text_area(
            FIELD_LABELS["notes"],
            value=current.get("notes") or "",
            placeholder="למשל: מעל רדיאטור, מול חלון גדול",
            max_chars=2000,
            key=f"{key_prefix}_notes",
        )

        if st.form_submit_button("שמירת תנאי הגידול", type="primary", icon=":material/save:"):
            on_save(
                {
                    "location_type": location,
                    "light_level": light,
                    "light_direction": direction,
                    "temperature_c": temperature,
                    "humidity_percent": humidity,
                    "room": room.strip() or None,
                    "notes": notes.strip() or None,
                }
            )
