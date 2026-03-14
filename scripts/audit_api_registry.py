#!/usr/bin/env python3
"""
audit_api_registry.py — Scan all projects for API usage patterns and report
anything not reflected in ~/claude/API_REGISTRY.md.

Usage:
    python scripts/audit_api_registry.py

Prints a report of findings. Does not modify files — Claude handles the update.
"""

import os
import re
import subprocess
from pathlib import Path

PROJECTS = {
    "smebot":              Path("~/claude/smebot").expanduser(),
    "investment-analyst":  Path("~/claude/investment-analyst").expanduser(),
    "spending-monitor":    Path("~/claude/spending-monitor").expanduser(),
    "miles-optimizer":     Path("~/claude/miles-optimizer").expanduser(),
    "playo":               Path("~/claude/playo").expanduser(),
}

REGISTRY = Path("~/claude/API_REGISTRY.md").expanduser()

# Patterns: (label, regex)
API_PATTERNS = [
    ("Anthropic Claude",    r"anthropic|claude-haiku|claude-sonnet|claude-opus"),
    ("OpenAI",              r"openai|gpt-4|gpt-3\.5"),
    ("Telegram Bot API",    r"telegram|bot_token|TELEGRAM_BOT_TOKEN"),
    ("yfinance",            r"yfinance|yf\.Ticker"),
    ("FMP",                 r"financialmodelingprep|FMP_API_KEY"),
    ("OpenInsider",         r"openinsider\.com"),
    ("S3 / Backblaze",      r"boto3|s3_endpoint|S3_ACCESS_KEY|backblaze"),
    ("Meta / WhatsApp",     r"WA_ACCESS_TOKEN|whatsapp|meta.*api|graph\.facebook"),
    ("AWS S3 SDK",          r"@aws-sdk/client-s3|s3-request-presigner"),
    ("Stripe",              r"stripe"),
    ("Twilio",              r"twilio"),
    ("SendGrid",            r"sendgrid"),
    ("Google Maps",         r"google.*maps|maps\.googleapis"),
    ("Forge API",           r"BUILT_IN_FORGE_API|forge.*api"),
    ("IBKR",                r"ib_insync|ibkr|IBKR_PORT"),
    ("OneDrive / MSAL",     r"msal|onedrive|microsoft.*graph"),
]

SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "venv", "dist", "build", ".next"}
SKIP_EXTS = {".lock", ".png", ".jpg", ".svg", ".ico", ".db", ".sqlite", ".pyc", ".pdf"}


def scan_project(project: str, root: Path) -> dict[str, list[str]]:
    """Return {api_label: [file_path, ...]} for all matches found."""
    if not root.exists():
        return {}

    hits: dict[str, list[str]] = {}

    for path in root.rglob("*"):
        if any(skip in path.parts for skip in SKIP_DIRS):
            continue
        if path.suffix in SKIP_EXTS or not path.is_file():
            continue
        try:
            text = path.read_text(errors="ignore")
        except Exception:
            continue

        for label, pattern in API_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                hits.setdefault(label, []).append(str(path.relative_to(root)))

    return hits


def registry_mentions(label: str) -> bool:
    """Check if the registry already documents this API for any project."""
    if not REGISTRY.exists():
        return False
    text = REGISTRY.read_text()
    return label.split("/")[0].strip().lower() in text.lower()


def main() -> None:
    print("=" * 60)
    print("API Registry Audit")
    print("=" * 60)

    all_findings: dict[str, dict[str, list[str]]] = {}

    for project, root in PROJECTS.items():
        findings = scan_project(project, root)
        if findings:
            all_findings[project] = findings

    # Report by project
    new_findings = []
    for project, findings in all_findings.items():
        print(f"\n### {project}")
        for label, files in sorted(findings.items()):
            in_registry = registry_mentions(label)
            status = "OK" if in_registry else "NOT IN REGISTRY"
            print(f"  [{status}] {label}")
            for f in files[:3]:  # show up to 3 example files
                print(f"    - {f}")
            if not in_registry:
                new_findings.append((project, label, files))

    print("\n" + "=" * 60)
    if new_findings:
        print(f"FOUND {len(new_findings)} API(s) not in registry:\n")
        for project, label, files in new_findings:
            print(f"  - [{project}] {label}")
            print(f"    Example: {files[0]}")
        print("\nUpdate ~/claude/API_REGISTRY.md to document these.")
    else:
        print("All detected APIs are documented in API_REGISTRY.md.")
    print("=" * 60)


if __name__ == "__main__":
    main()
