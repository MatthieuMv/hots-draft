"""Hero data API and desktop overlay entry point."""

from hots_draft.scraper import ensure_data_ready, load_heroes

__all__ = ["ensure_data_ready", "load_heroes"]


def main() -> None:
    """Launch the overlay and initialize its hero library in the background."""
    from hots_draft.overlay import main as overlay_main

    overlay_main()
