import os
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from hots_draft import overlay
from hots_draft.overlay import OverlayWindow
from hots_draft.scraper import BASE_URL, parse_hero


@pytest.fixture(scope="module")
def app():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    application = QApplication.instance() or QApplication([])
    yield application


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(overlay, "download_portraits", lambda *_: 0)
    monkeypatch.setattr(overlay.OverlayWindow, "request_talent_icons", lambda *_: None)


@pytest.fixture
def window(app, tmp_path):
    widget = OverlayWindow(tmp_path)
    source = (Path(__file__).parent / "fixtures" / "jaina.html").read_text(
        encoding="utf-8"
    )
    hero = parse_hero(
        source, {"id": "jaina", "name": "Jaina", "url": BASE_URL + "jaina-build-guide"}
    )
    widget.set_heroes({"jaina": hero})
    widget.map_combo.setCurrentIndex(widget.map_combo.findData("infernal-shrines"))
    widget.first_combo.setCurrentIndex(widget.first_combo.findData(True))
    widget.begin_draft()
    widget.search.setText("Jaina")
    widget.show()
    app.processEvents()
    yield widget
    widget.close()


def test_selection_assignment_and_duplicate_prevention(window):
    assert window.selected_hero == "jaina"
    window.assign_button.click()
    assert window.draft.slots["ally_bans"][0] == "jaina"
    assert window.active_slot == ("enemy_bans", 0)
    window.slot_buttons["enemies", 0].click()
    assert not window.assign_button.isEnabled()
    window.clear_slot()
    assert not window.draft.unavailable


def test_map_and_search_filters(window):
    window.role_buttons["Ranged Assassin"].click()
    assert window.hero_list.count() == 1
    assert window.recommendations[0].reasons == ["Strong on this battleground"]
    window.search.setText("no match")
    assert window.hero_list.count() == 0
    window.search.clear()
    assert window.hero_list.count() == 1


def test_saved_draft_is_restored(window, app):
    window.assign_selected()
    another = OverlayWindow(window.data_dir)
    another.set_heroes(window.heroes)
    assert another.draft.slots["ally_bans"][0] == "jaina"
    assert another.active_slot == ("enemy_bans", 0)
    another.close()


def test_collapse_pin_and_rendered_details(window, monkeypatch):
    contents = []

    def inspect(dialog):
        contents.append(dialog.findChild(overlay.QTextBrowser).toPlainText())
        return 0

    monkeypatch.setattr(overlay.QDialog, "exec", inspect)
    window.show_details()
    assert "Fingers of Frost" in contents[0]
    assert "Countered by" in contents[0]
    window.toggle_compact()
    assert window.body.isHidden()
    assert window.width() == 280 and window.height() == 48
    window.toggle_compact()
    assert not window.body.isHidden()
    window.pin.setChecked(False)
    assert not window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint


def test_corrupt_saved_draft_does_not_prevent_loading(window):
    (window.data_dir / "draft-session.json").write_text("bad json", encoding="utf-8")
    window.set_heroes(window.heroes)
    assert "could not be restored" in window.status.text()


def test_background_loading_failure_and_retry(window, app, monkeypatch, tmp_path):
    attempts = []

    def initialize(_):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("Connection unavailable")
        return tmp_path

    monkeypatch.setattr(overlay, "ensure_data_ready", initialize)
    monkeypatch.setattr(overlay, "load_heroes", lambda _: window.heroes)
    widget = OverlayWindow(tmp_path / "loading")
    widget.show()
    widget.start_loading()
    assert widget.loader.wait(2000)
    app.processEvents()
    assert "Connection unavailable" in widget.status.text()
    assert not widget.retry.isHidden()
    widget.retry.click()
    assert widget.loader.wait(2000)
    app.processEvents()
    assert len(widget.heroes) == 1
    assert widget.retry.isHidden()
    assert widget.portrait_loader.wait(2000)
    app.processEvents()
    widget.close()


def test_enter_picks_and_advances_slot(window):
    QTest.keyClick(window.search, Qt.Key.Key_Return)
    assert window.draft.slots["ally_bans"][0] == "jaina"
    assert window.active_slot == ("enemy_bans", 0)
    assert window.search.text() == ""
    window.search.setText("Jaina")
    assert window.hero_list.count() == 0
    assert not window.assign_button.isEnabled()


def test_ban_mode_and_one_click_suggestion(window):
    window.search.clear()
    window.map_combo.setCurrentIndex(window.map_combo.findData("infernal-shrines"))
    assert window.active_slot == ("ally_bans", 0)
    window.assign_button.click()
    assert window.draft.slots["ally_bans"][0] == "jaina"
    assert window.active_slot == ("enemy_bans", 0)


def test_why_button_explains_without_assigning(window, monkeypatch):
    window.search.clear()
    window.map_combo.setCurrentIndex(window.map_combo.findData("infernal-shrines"))
    texts = []

    def inspect(dialog):
        texts.extend(label.text() for label in dialog.findChildren(overlay.QLabel))
        return 0

    monkeypatch.setattr(overlay.QDialog, "exec", inspect)
    window.why_button.click()
    assert any("Strong on this battleground" in text for text in texts)
    assert not window.draft.unavailable


def test_close_during_loading_finishes_without_destroying_thread(
    app, monkeypatch, tmp_path
):
    import threading

    gate = threading.Event()

    def initialize(_):
        gate.wait(2)
        raise RuntimeError("Stopped")

    monkeypatch.setattr(overlay, "ensure_data_ready", initialize)
    widget = OverlayWindow(tmp_path)
    widget.show()
    widget.start_loading()
    widget.close()
    assert widget.closing and widget.isHidden()
    gate.set()
    assert widget.loader.wait(2000)
    app.processEvents()
    assert not widget.loader.isRunning()


def test_setup_requires_map_and_first_team(app, tmp_path, window):
    widget = OverlayWindow(tmp_path / "setup")
    widget.set_heroes(window.heroes)
    assert not widget.start_button.isEnabled()
    assert not widget.first_combo.isEnabled()
    widget.map_combo.setCurrentIndex(widget.map_combo.findData("infernal-shrines"))
    assert widget.first_combo.isEnabled()
    assert not widget.start_button.isEnabled()
    widget.first_combo.setCurrentIndex(widget.first_combo.findData(False))
    assert widget.start_button.isEnabled()
    widget.start_button.click()
    assert widget.active_slot == ("enemy_bans", 0)
    assert widget.setup_panel.isHidden()
    assert not widget.flow_panel.isHidden()
    widget.close()


def test_completed_draft_hides_action_controls(window):
    from copy import deepcopy

    heroes = {}
    for i in range(16):
        heroes[str(i)] = deepcopy(window.heroes["jaina"])
        heroes[str(i)]["name"] = f"Hero {i}"
    window.heroes = heroes
    for i in range(16):
        window.assign_hero(str(i))
    assert window.draft.completed
    assert window.active_slot is None
    assert window.finder_panel.isHidden()
    assert window.selection.isHidden()
    assert "Draft complete" in window.target.text()
    window.undo_button.click()
    assert not window.draft.completed
    assert not window.selection.isHidden()
    assert window.hero_list.count() == 1


def test_role_icon_filters_toggle_and_slot_badge(window):
    window.search.clear()
    window.role_buttons["Healer"].click()
    assert window.hero_list.count() == 0
    assert window.role_buttons["Healer"].isChecked()
    window.role_buttons["Healer"].click()
    assert window.selected_role is None
    assert window.hero_list.count() == 1
    for _ in range(4):
        window.skip_ban()
    window.assign_selected()
    assert window.slot_buttons["allies", 0].iconSize().width() == 66
    assert not window.slot_buttons["allies", 0].icon().isNull()
    assert "Ranged Assassin" in window.slot_buttons["allies", 0].toolTip()


def test_list_uses_role_metadata_instead_of_role_text(window):
    item = window.hero_list.item(0)
    assert item.data(Qt.ItemDataRole.UserRole + 1) == "Ranged Assassin"
    assert "Ranged Assassin" not in item.text()
    assert "Ranged Assassin" in item.toolTip()


def test_right_click_build_popup_does_not_assign(window, monkeypatch):
    texts = []

    def inspect(dialog):
        texts.extend(b.toPlainText() for b in dialog.findChildren(overlay.QTextBrowser))
        return 0

    monkeypatch.setattr(overlay.QDialog, "exec", inspect)
    item_rect = window.hero_list.visualItemRect(window.hero_list.item(0))
    window.list_build_popup(item_rect.center())
    assert any("Fingers of Frost" in text for text in texts)
    assert not window.draft.history


def test_completed_build_view_changes_with_picked_hero(window):
    from copy import deepcopy

    window.heroes = {str(i): deepcopy(window.heroes["jaina"]) for i in range(16)}
    for i, hero in window.heroes.items():
        hero["name"] = f"Hero {i}"
    for i in range(16):
        window.assign_hero(str(i))
    assert window.hero_list.count() == 10
    assert not window.build_panel.isHidden()
    assert "Fingers of Frost" in window.build_panel.browser.toPlainText()
    hero_id = window.draft.slots["enemies"][0]
    window.slot_buttons["enemies", 0].click()
    assert window.selected_hero == hero_id
    assert window.build_panel.hero_id == hero_id
    assert "fit" in window.hero_list.item(0).text().lower()
    window.undo_button.click()
    assert window.build_panel.isHidden()


def test_build_strip_embeds_cached_talent_icons(window):
    from PySide6.QtGui import QColor, QPixmap

    from hots_draft.talent_icons import icon_path

    talent = window.heroes["jaina"]["builds"][0]["talent_tiers"][0]["talents"][0]
    path = icon_path(window.talent_icon_dir, talent["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    pixmap = QPixmap(40, 40)
    pixmap.fill(QColor("#00aabb"))
    assert pixmap.save(str(path))
    window.load_builds(window.build_panel, "jaina")
    html = window.build_panel.browser.toHtml()
    assert path.name in html
    assert 'width="40"' in html
    assert "Fingers of Frost" in window.build_panel.browser.toPlainText()


def test_team_slot_fit_color_and_tooltip_update_with_draft(window):
    from copy import deepcopy

    window.search.clear()
    window.draft.assign("allies", 0, "jaina")
    window.update_slots()
    slot = window.slot_buttons["allies", 0]
    assert "Draft fit: +3" in slot.toolTip()
    initial_style = slot.styleSheet()
    enemy = deepcopy(window.heroes["jaina"])
    enemy["name"] = "Enemy"
    enemy["counters"]["heroes"] = [{"id": "jaina"}]
    enemy["synergies"]["heroes"] = []
    window.heroes["enemy"] = enemy
    window.draft.assign("enemies", 0, "enemy")
    window.update_slots()
    assert "Draft fit: +8" in slot.toolTip()
    assert "Counters Enemy" in slot.toolTip()
    assert slot.styleSheet() != initial_style
    window.heroes["jaina"]["counters"]["heroes"] = [{"id": "enemy"}]
    enemy["counters"]["heroes"] = []
    window.update_slots()
    assert "Draft fit: -3" in slot.toolTip()
    assert "Threatened by Enemy" in slot.toolTip()
    assert "#cf7f86" in slot.styleSheet()
    window.draft.assign("allies", 0, None)
    window.update_slots()
    assert "Draft fit" not in slot.toolTip()
    assert slot.styleSheet() == "padding: 4px;"


def test_fit_colors_are_neutral_and_bounded():
    assert overlay.draft_fit_colors(0)[0] == "#1a2533"
    assert overlay.draft_fit_colors(20) == overlay.draft_fit_colors(100)
    assert overlay.draft_fit_colors(-12) == overlay.draft_fit_colors(-100)
