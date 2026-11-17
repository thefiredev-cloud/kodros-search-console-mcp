#!/usr/bin/env python3
"""Replace the client secret inside the saved Desktop OAuth client JSON.

Use this after rotating the secret in the Google Cloud console:
    uv run python set-client-secret.py

The new secret is read from a hidden prompt, so it never appears in shell
history or terminal output. The client file path comes from
GOOGLE_API_MCP_CLIENT_FILE (default: ~/.config/google-api-mcp/client_secret.json).
"""
from __future__ import annotations

import getpass
import json
import os
import sys

from server import CLIENT_FILE


def main() -> None:
    if not CLIENT_FILE.is_file():
        raise SystemExit(
            f"OAuth client file not found: {CLIENT_FILE}. Save the Desktop OAuth "
            "client JSON there first, or set GOOGLE_API_MCP_CLIENT_FILE."
        )
    secret = getpass.getpass("New client secret (hidden input): ").strip()
    if not secret or any(character.isspace() for character in secret):
        raise SystemExit("The client secret is empty or contains whitespace. Nothing was changed.")

    config = json.loads(CLIENT_FILE.read_text(encoding="utf-8"))
    section = config.get("installed")
    if not isinstance(section, dict):
        raise SystemExit(
            f"{CLIENT_FILE} has no 'installed' section. Use a Desktop OAuth client JSON."
        )
    if secret == section.get("client_secret", ""):
        raise SystemExit("The client secret is unchanged. Nothing was changed.")
    section["client_secret"] = secret
    temporary = CLIENT_FILE.with_suffix(".json.tmp")
    file_descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(config))
    os.replace(temporary, CLIENT_FILE)
    os.chmod(CLIENT_FILE, 0o600)
    print(f"Updated the client secret in {CLIENT_FILE}.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
