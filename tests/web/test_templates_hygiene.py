"""Template hygiene checks: extends base.html, no inline styles or CDN URLs."""

import re
from pathlib import Path


def scan_templates(templates_dir: Path) -> dict[str, str]:
    """Load all HTML templates from a directory.

    Returns a dict mapping file path (relative to templates_dir) to file contents.
    """
    result = {}
    for template_file in templates_dir.rglob("*.html"):
        rel_path = template_file.relative_to(templates_dir)
        result[str(rel_path)] = template_file.read_text()
    return result


def check_template_extends(content: str) -> bool:
    """Check if a template extends base.html."""
    # Look for {% extends "base.html" %} or {% extends 'base.html' %}
    return bool(re.search(r'{%\s*extends\s+["\']base\.html["\']\s*%}', content))


def check_no_style_tag(content: str) -> bool:
    """Check if template contains <style (no inline styles)."""
    return bool(re.search(r"<style", content, re.IGNORECASE))


def check_no_cdn_url(content: str) -> bool:
    """Check if template contains CDN URLs (unpkg, cdn, etc)."""
    return bool(re.search(r"(unpkg|cdn)", content, re.IGNORECASE))


def test_templates_extend_base():
    """Non-component, non-fragment templates must extend base.html."""
    templates_dir = Path(__file__).parent.parent.parent / "src" / "sonar" / "web" / "templates"
    templates = scan_templates(templates_dir)

    # Fragment templates (rendered by HTMX/OOB swaps) are exempt
    fragments = {"import_results.html", "components/nav_badge.html"}

    # Component templates are exempt
    components_dir = "components"

    failures = []
    for rel_path, content in templates.items():
        # Skip base.html itself
        if rel_path == "base.html":
            continue

        # Skip fragments
        if rel_path in fragments:
            continue

        # Skip components
        if rel_path.startswith(components_dir + "/"):
            continue

        # All other templates must extend base.html
        if not check_template_extends(content):
            failures.append(f"{rel_path} does not extend base.html")

    assert not failures, "\n".join(failures)


def test_no_inline_styles():
    """Templates must not contain <style tags."""
    templates_dir = Path(__file__).parent.parent.parent / "src" / "sonar" / "web" / "templates"
    templates = scan_templates(templates_dir)

    failures = []
    for rel_path, content in templates.items():
        if check_no_style_tag(content):
            failures.append(f"{rel_path} contains <style tag")

    assert not failures, "\n".join(failures)


def test_no_cdn_urls():
    """Templates must not contain CDN URLs."""
    templates_dir = Path(__file__).parent.parent.parent / "src" / "sonar" / "web" / "templates"
    templates = scan_templates(templates_dir)

    failures = []
    for rel_path, content in templates.items():
        if check_no_cdn_url(content):
            failures.append(f"{rel_path} contains CDN URL")

    assert not failures, "\n".join(failures)


def test_hygiene_catches_style_tag(tmp_path):
    """Verify hygiene test catches <style tags (sanity check)."""
    template_file = tmp_path / "test.html"
    template_file.write_text("""{% extends "base.html" %}
{% block content %}
<style>
    .test { color: red; }
</style>
{% endblock %}
""")

    templates = scan_templates(tmp_path)
    has_style = any(check_no_style_tag(content) for content in templates.values())
    assert has_style, "Hygiene check should catch <style tags"


def test_hygiene_catches_missing_extends(tmp_path):
    """Verify hygiene test catches missing extends (sanity check)."""
    template_file = tmp_path / "test.html"
    template_file.write_text("""<html>
<body>Test</body>
</html>""")

    templates = scan_templates(tmp_path)
    missing_extends = any(
        rel_path != "base.html" and not check_template_extends(content)
        for rel_path, content in templates.items()
    )
    assert missing_extends, "Hygiene check should catch missing extends"
