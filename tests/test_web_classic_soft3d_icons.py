"""Presentation-only Soft 3D icons must preserve classic tool wiring."""
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "geostudio" / "web_app" / "static"


class IconParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.buttons = {}
        self.button = None
        self.gradients = []
        self.fills = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "button":
            self.button = attrs.get("id")
            if self.button:
                self.buttons[self.button] = {
                    "class": attrs.get("class", ""), "icons": 0}
        if tag == "svg" and "soft3d-icon" in attrs.get("class", "").split():
            assert attrs.get("aria-hidden") == "true"
            assert attrs.get("focusable") == "false"
            if self.button:
                self.buttons[self.button]["icons"] += 1
        if tag.lower() == "lineargradient":
            self.gradients.append(attrs["id"])
        if attrs.get("fill", "").startswith("url(#gs-soft3d-"):
            self.fills.append(attrs["fill"][5:-1])

    def handle_endtag(self, tag):
        if tag == "button":
            self.button = None


def test_soft3d_tool_coverage_and_unique_gradient_ids():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    parser = IconParser()
    parser.feed(html)
    assert len(parser.ids) == len(set(parser.ids))
    ribbon = {key: value for key, value in parser.buttons.items()
              if key.startswith("tool-") and "tool-button" in value["class"].split()}
    assert len(ribbon) == 39
    assert all(value["icons"] == 1 for value in ribbon.values())
    floating = {key: value for key, value in parser.buttons.items()
                if key.startswith("float-")}
    assert len(floating) == 10
    assert all(value["icons"] == 1 for value in floating.values())
    assert parser.buttons["btn-theme"]["icons"] == 2
    assert parser.buttons["btn-export"]["icons"] == 1
    assert "btn-export-label" in parser.ids
    assert len(parser.gradients) == 60
    assert sorted(parser.gradients) == sorted(parser.fills)


def test_soft3d_css_keeps_reduced_motion_and_theme_switch():
    css = (ROOT / "styles.css").read_text(encoding="utf-8")
    js = (ROOT / "map.js").read_text(encoding="utf-8")
    assert "prefers-reduced-motion:reduce" in css
    assert 'body[data-theme="dark"] .topbar .theme-moon' in css
    assert 'body[data-theme="light"] .topbar .theme-sun' in css
    assert '$("btn-export-label").textContent' in js
    assert "themeButton.textContent=" not in js
