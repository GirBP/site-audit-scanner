#!/usr/bin/env python3
"""Small positive/negative contract test for site_audit.py."""

from pathlib import Path
import json
import subprocess
import sys
import tempfile


SCRIPT = Path(__file__).with_name("site_audit.py")


def page(title: str, canonical: str, body: str, robots: str = "index, follow") -> str:
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<meta name="description" content="A complete and useful description for deterministic scanner testing.">
<meta name="robots" content="{robots}">
<link rel="canonical" href="{canonical}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="A complete social description for this fixture page.">
<meta property="og:url" content="{canonical}">
<meta property="og:type" content="website">
<meta property="og:image" content="https://example.test/og.jpg">
<meta name="twitter:card" content="summary_large_image">
<script type="application/ld+json">{{"@context":"https://schema.org","@type":"WebPage"}}</script>
</head><body><main>{body}</main></body></html>"""


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "site"
        out = Path(tmp) / "report"
        root.mkdir()
        (root / "image.jpg").write_bytes(b"fixture")
        (root / "index.html").write_text(
            page(
                "Fixture home page",
                "https://example.test/",
                """<h1>Fixture home</h1>
                <p>This fixture contains enough meaningful words to exercise visible text metrics.
                It describes a safe read only website audit workflow with links images forms metadata
                structured data and accessible controls for repeatable validation across pages.</p>
                <a href="about.html">About</a>
                <img src="image.jpg" alt="Fixture" width="10" height="10">
                <form><label>Name <input name="name" required></label>
                <button type="submit">Send</button></form>""",
            ),
            encoding="utf-8",
        )
        (root / "about.html").write_text(
            page(
                "Fixture about page",
                "https://example.test/about.html",
                """<h1>About fixture</h1>
                <p>This second page intentionally links to a missing target so the negative contract
                proves the scanner catches broken internal links and records exact evidence.</p>
                <a href="missing.html">Missing</a>""",
            ),
            encoding="utf-8",
        )
        (root / "legacy.html").write_text(
            page(
                "Legacy redirect page",
                "https://example.test/",
                "<p>Intentional non-indexable utility page.</p>",
                robots="noindex, follow",
            ),
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                str(root),
                "--output",
                str(out),
                "--max-pages",
                "10",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise AssertionError(result.stderr or result.stdout)
        audit = json.loads((out / "audit.json").read_text(encoding="utf-8"))
        rules = [(item["rule"], item["severity"], item["url"]) for item in audit["findings"]]
        assert any(rule == "INTERNAL_LINK_BROKEN" and severity == "high" for rule, severity, _ in rules)
        assert not any(
            rule == "FORM_LABEL_MISSING" and url.endswith("/index.html")
            for rule, _, url in rules
        )
        assert not any(
            rule == "H1_MISSING" and severity == "high" and url.endswith("/legacy.html")
            for rule, severity, url in rules
        )
        assert (out / "summary.md").is_file()
        assert (out / "report.html").is_file()
        print("test_site_audit: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
