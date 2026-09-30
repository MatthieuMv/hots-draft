"""Render a reproducible preview without changing the user's saved draft."""

import os
import tempfile
from pathlib import Path

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from hots_draft.overlay import OverlayWindow
from hots_draft.scraper import ensure_data_ready, load_heroes


def main():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication([])
    # Qt's offscreen platform does not enumerate Windows system fonts.
    font_dir = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for filename in ("segoeui.ttf", "segoeuib.ttf"):
        if (font_dir / filename).exists():
            QFontDatabase.addApplicationFont(str(font_dir / filename))
    heroes = load_heroes(ensure_data_ready("data"))
    output = Path("artifacts/overlay-preview.png")
    output.parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as session:
        window = OverlayWindow(Path(session), portrait_dir=Path("data/portraits"))
        window.talent_icon_dir = Path("data/talent-icons")
        window.request_talent_icons = lambda *_: None
        window.set_heroes(heroes)
        window.map_combo.setCurrentIndex(window.map_combo.findData("infernal-shrines"))
        window.show()
        app.processEvents()
        window.grab().save("artifacts/overlay-setup.png")
        window.first_combo.setCurrentIndex(window.first_combo.findData(True))
        window.begin_draft()
        for id_ in (
            "azmodan",
            "abathur",
            "samuro",
            "medivh",
            "johanna",
            "alarak",
            "valla",
        ):
            window.assign_hero(id_)
        app.processEvents()
        if not window.grab().save(str(output)):
            raise RuntimeError("Could not save overlay preview")
        window.assign_hero("anduin")
        window.assign_hero("jaina")
        app.processEvents()
        window.grab().save("artifacts/overlay-bans.png")
        window.toggle_compact()
        app.processEvents()
        window.grab().save("artifacts/overlay-compact.png")
        window.toggle_compact()
        for hero_id in (
            "muradin",
            "diablo",
            "rehgar",
            "dehaka",
            "falstad",
            "sylvanas",
            "thrall",
        ):
            window.assign_hero(hero_id)
        app.processEvents()
        window.grab().save("artifacts/overlay-completed.png")
        window.close()
    print(output.resolve())


if __name__ == "__main__":
    main()
