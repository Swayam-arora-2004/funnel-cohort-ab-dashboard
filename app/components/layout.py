"""One CSS override: let the BROWSER WINDOW scroll, instead of Streamlit's inner container.

Why this exists, and why it is worth an exception to the "no CSS against the framework" rule
set out in DECISIONS D-019:

By default Streamlit gives `<body>` a height of 0 and makes `<main data-testid="stMain">` a
fixed-height element with `overflow: auto`. The browser window therefore never scrolls and
never shows a page scrollbar -- all scrolling happens inside one nested div. Measured on this
app before the fix:

    document.documentElement.scrollHeight === clientHeight === 800   (window not scrollable)
    body height                            === 0px
    main.scrollHeight                      === 1533px               (the real content)

That architecture has two consequences we actually hit:

  1. The sidebar is a SEPARATE scroll region, so a wheel over it moves the page by 0px.
     Measured. At 300px it is about a quarter of a 1280px window, and it is nearly empty.
  2. Any browser or input device that does not deliver wheel events to that nested div --
     and Swayam's Chrome is one -- simply cannot scroll the page at all. There is no page
     scrollbar to fall back on, because the window is not scrollable.

The override below restores ordinary document scrolling: one scrollbar, on the window, exactly
like every other web page. Verified with real (trusted) mouse-wheel events after applying it:

    wheel over content  -> window scrolled 700px
    wheel over sidebar  -> window scrolled 600px   (the dead zone is gone)
    wheel to the end    -> scrollY 733 === max 733 (the bottom is reachable)

**Why this is an acceptable exception.** D-019 rejected CSS aimed at Streamlit's generated
emotion class names (`.st-emotion-cache-dplwqh`), which change between releases. These
selectors are `data-testid` attributes, which Streamlit maintains as its documented testing
surface and changes far more rarely. More importantly the failure mode is graceful: if a
future release renames one, the rule stops matching and the app falls back to Streamlit's
normal inner scrolling -- the same behaviour it has today, not a broken layout. A font-shrink
hack would have failed by visibly breaking the page; this one fails by doing nothing.

See DECISIONS D-021.
"""

from __future__ import annotations

import streamlit as st

_WINDOW_SCROLL_CSS = """
<style>
/* Let the document grow and the window scroll, instead of a fixed-height inner div. */
html, body {
    height: auto !important;
    overflow: visible !important;
}
[data-testid="stApp"],
[data-testid="stAppViewContainer"] {
    position: static !important;
    height: auto !important;
    min-height: 100vh !important;
    overflow: visible !important;
}
[data-testid="stMain"] {
    height: auto !important;
    overflow: visible !important;
}
/* The sidebar scrolls with the document like ordinary page content. `align-self: stretch`
   makes its background run the full height of the page rather than stopping at 100vh and
   leaving a pale gap below it. */
[data-testid="stSidebar"] {
    position: static !important;
    height: auto !important;
    min-height: 100vh !important;
    align-self: stretch !important;
}
[data-testid="stSidebarContent"] {
    height: auto !important;
    min-height: 100vh !important;
    overflow: visible !important;
}
</style>
"""


def use_window_scrolling() -> None:
    """Call once per page, immediately after `st.set_page_config`."""
    st.markdown(_WINDOW_SCROLL_CSS, unsafe_allow_html=True)
