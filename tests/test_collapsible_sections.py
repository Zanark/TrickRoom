from unittest.mock import Mock

import pytest

from trickroom.studio import CollapsibleSection, Studio


@pytest.fixture
def section():
    group = CollapsibleSection.__new__(CollapsibleSection)
    group.title = "03 / RIG MOTION"
    group.expanded = True
    group.body = Mock()
    group.body.__str__ = Mock(return_value=".panel.section.body")
    group.header = Mock()
    group.focus_get = Mock(return_value=None)
    return group


def test_collapse_hides_widgets_without_destroying_them(section):
    body = section.body
    section.set_expanded(False)
    assert not section.expanded
    section.header.configure.assert_called_once_with(text="[+] 03 / RIG MOTION")
    body.pack_forget.assert_called_once()
    body.destroy.assert_not_called()
    assert section.body is body


def test_expand_restores_the_same_body(section):
    section.set_expanded(False)
    section.set_expanded(True)
    assert section.expanded
    section.body.pack.assert_called_once_with(fill="x")
    section.header.configure.assert_called_with(text="[-] 03 / RIG MOTION")
    section.body.destroy.assert_not_called()


def test_toggle_and_keyboard_activation_keep_state_and_indicator_consistent(section):
    section.toggle()
    assert not section.expanded
    assert section._toggle_from_keyboard(None) == "break"
    assert section.expanded
    section.header.configure.assert_called_with(text="[-] 03 / RIG MOTION")


@pytest.mark.parametrize(
    "focused_path", [".panel.section.body.entry", ".panel.section.body.row.scale"]
)
def test_collapsing_focused_controls_returns_focus_to_the_header(section, focused_path):
    section.focus_get.return_value = focused_path
    section.set_expanded(False)
    section.header.focus_set.assert_called_once()


def test_collapsing_does_not_steal_focus_from_another_section(section):
    section.focus_get.return_value = ".panel.section.body2.entry"
    section.set_expanded(False)
    section.header.focus_set.assert_not_called()


def test_individual_section_does_not_change_its_peer(section):
    other = Mock(expanded=True)
    section.toggle()
    assert other.expanded
    other.set_expanded.assert_not_called()


@pytest.mark.parametrize("expanded", [False, True])
def test_bulk_toggle_changes_layout_only_and_collapse_returns_to_top(expanded):
    app = Studio.__new__(Studio)
    app.sections = {name: Mock() for name in ("input", "model", "tracking")}
    app.controls_canvas = Mock()
    app.runtime = Mock()
    app.renderer = Mock()
    runtime, renderer = app.runtime, app.renderer
    app.set_sections_expanded(expanded)
    for section in app.sections.values():
        section.set_expanded.assert_called_once_with(expanded)
    if expanded:
        app.controls_canvas.yview_moveto.assert_not_called()
    else:
        app.controls_canvas.yview_moveto.assert_called_once_with(0)
    assert app.runtime is runtime and app.renderer is renderer
    runtime.stop.assert_not_called()
    renderer.reset_motion.assert_not_called()
