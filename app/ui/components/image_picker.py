"""Choosing photographs: from the device, or taken now.

`st.file_uploader` was the only way in. On a phone that is already adequate — the
OS picker offers "Take Photo" — but on a desktop it means finding a file, and on
either it means leaving the app to get the picture of the thing you are looking
at right now. A health check in particular is *always* about something just
noticed.

`st.camera_input` fills that in. Two things shape how it is used here:

* **It returns one photograph at a time**, not a list, so captures accumulate in
  session state rather than living in the widget. That is also what makes a
  confirm step natural: the capture is previewed and kept deliberately, so a
  mistimed shot never silently joins the batch.
* **It needs a secure context.** `getUserMedia` is refused over plain http, so
  the tab is absent on `http://192.168.x.x:8501` — a phone on the LAN pointed at
  a development server. It works on `localhost` and over https, which is every
  deployment. The uploader is always present, so nothing is ever unreachable;
  the camera is an addition, never the only route.

Resolution is requested at 1080p rather than left to the widget's display size:
the image pipeline works to a 1600px long edge and identification quality is the
product, so a camera capture sized to a narrow column would be a poor photograph
by construction.
"""

from __future__ import annotations

from typing import Any, Literal

import streamlit as st

CAPTURE_RESOLUTION: Literal["480p", "720p", "1080p"] = "1080p"


def _bucket(key_prefix: str) -> str:
    return f"{key_prefix}_captured"


def captured(key_prefix: str) -> list[Any]:
    """Photographs taken with the camera and kept, for this screen."""
    return st.session_state.setdefault(_bucket(key_prefix), [])


def clear(key_prefix: str) -> None:
    st.session_state.pop(_bucket(key_prefix), None)


def _remember(key_prefix: str, photo: Any) -> None:
    captured(key_prefix).append(photo)
    # Bump the widget key so `camera_input` resets to a live preview instead of
    # holding the shot just kept - otherwise the next confirm would add the same
    # photograph again.
    st.session_state[f"{key_prefix}_camera_round"] = _round(key_prefix) + 1


def _round(key_prefix: str) -> int:
    return int(st.session_state.get(f"{key_prefix}_camera_round", 0))


def image_picker(
    *,
    key_prefix: str,
    max_images: int,
    upload_label: str = "תמונות מהמכשיר",
    help_text: str | None = None,
) -> list[Any]:
    """Uploaded files and kept captures, as one list.

    The caller sees a single list of file-like objects and does not care where any
    of them came from: `st.camera_input` and `st.file_uploader` both return
    `UploadedFile`, so `.name`, `.getvalue()` and `.type` work the same.
    """
    kept = captured(key_prefix)
    remaining = max_images - len(kept)

    device_tab, camera_tab = st.tabs(["העלאת תמונות", "צילום"])

    with device_tab:
        uploads = st.file_uploader(
            upload_label,
            type=["jpg", "jpeg", "png", "webp"],
            accept_multiple_files=True,
            key=f"{key_prefix}_uploads",
            help=help_text,
        )

    with camera_tab:
        if remaining <= 0:
            st.caption(f"נבחרו כבר {max_images} תמונות. אפשר להסיר אחת כדי לצלם עוד.")
        else:
            st.caption(
                "אם המצלמה לא נפתחת, כנראה שהעמוד נטען בלי חיבור מאובטח. "
                "אפשר תמיד לצלם דרך האפליקציה ולהעלות מהמכשיר."
            )
            shot = st.camera_input(
                "צילום הצמח",
                key=f"{key_prefix}_camera_{_round(key_prefix)}",
                resolution=CAPTURE_RESOLUTION,
            )
            if shot is not None and st.button(
                "שמירת הצילום",
                key=f"{key_prefix}_keep_{_round(key_prefix)}",
                type="primary",
                icon=":material/add_a_photo:",
            ):
                # Kept deliberately. Adding on capture would mean every accidental
                # shot joins the batch and has to be found and removed.
                _remember(key_prefix, shot)
                st.rerun()

    if kept:
        st.caption(f"צילומים שנשמרו ({len(kept)})")
        for index, photo in enumerate(kept):
            row = st.container(horizontal=True)
            with row:
                st.image(photo, width=90)
                if st.button(
                    "הסרה",
                    key=f"{key_prefix}_drop_{index}",
                    icon=":material/close:",
                ):
                    kept.pop(index)
                    st.rerun()

    return [*(uploads or []), *kept]
