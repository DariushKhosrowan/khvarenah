"""Tests for release/SEO artifacts: the consolidated CI release workflow and the
GitHub Pages SEO landing page (docs/index.html).

These are the two files that carry the project's "easy install" and "SEO"
claims, so they get explicit automated checks.
"""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent

WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
INDEX = ROOT / "docs" / "index.html"


# ---------- release.yml ----------

def test_release_workflow_exists():
    assert WORKFLOW.exists(), "release.yml missing"


def test_release_workflow_triggers_on_release_tags():
    d = yaml.safe_load(WORKFLOW.read_text())
    # YAML 1.1 parses the bare key `on` as a boolean True
    on = d.get("on") or d.get(True)
    assert on is not None
    push = on.get("push") or {}
    tags = push.get("tags", [])
    assert any(str(t).startswith("v") for t in tags), "no v* tag trigger"


def test_release_workflow_builds_all_platforms_and_publishes():
    d = yaml.safe_load(WORKFLOW.read_text())
    jobs = d["jobs"]
    assert {"build-deb", "build-exe", "release"} <= set(jobs), "missing jobs"
    release_job = jobs["release"]
    assert set(release_job.get("needs", [])) == {"build-deb", "build-exe"}
    names = [s.get("name", "") for s in release_job["steps"]]
    assert any("Publish release" in n for n in names)
    assert any("Generate checksums" in n for n in names)


def test_release_workflow_triggers_on_dispatch_with_tag_input():
    d = yaml.safe_load(WORKFLOW.read_text())
    on = d.get("on") or d.get(True)
    dispatch = on.get("workflow_dispatch") or {}
    inputs = dispatch.get("inputs") or {}
    assert "tag" in inputs, "workflow_dispatch needs a tag input"


def test_release_workflow_has_no_invalid_yaml_1_1_key():
    # The whole file must parse; only the `on` key may be the bool quirk.
    d = yaml.safe_load(WORKFLOW.read_text())
    assert True in d, "expected the YAML 1.1 `on` quirk to appear"


# ---------- docs/index.html ----------

_HTML_SNIPPETS = [
    # (fragment, human label)
    ('<title>Khvarenah', "title tag"),
    ('name="description"', "meta description"),
    ('<link rel="canonical"', "canonical"),
    ('rel="sitemap"', "sitemap link"),
    ('og:image', "Open Graph image"),
    ('hreflang', "hreflang alternates"),
    ('application/ld+json', "JSON-LD structured data"),
    ('"@type": "SoftwareApplication"', "SoftwareApplication schema"),
    ('"@type": "FAQPage"', "FAQPage schema"),
]


@pytest.mark.parametrize("fragment,label", _HTML_SNIPPETS)
def test_seo_snippet_present(fragment, label):
    html = INDEX.read_text()
    assert fragment in html, f"SEO element missing: {label} ({fragment!r})"


def test_html_tags_balanced():
    html = INDEX.read_text()
    # non-void elements that must close
    for tag in ("div", "h1", "h2", "p", "a", "pre", "ol", "li", "script", "style"):
        opens = len(re.findall(rf"<{tag}[\s>]", html))
        closes = len(re.findall(rf"</{tag}>", html))
        assert opens == closes, f"<{tag}> open={opens} vs close={closes}"


def test_html_has_no_unclosed_head_body():
    html = INDEX.read_text()
    assert html.count("<html") == html.count("</html>")
    assert html.count("<head>") == html.count("</head>")
    assert html.count("<body>") == html.count("</body>")
