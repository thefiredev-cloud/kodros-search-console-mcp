# Build guide: kodros-search-console-mcp

## You need

- Python 3.11 or newer and [uv](https://docs.astral.sh/uv/).
- A Google Cloud project with the Search Console API and the Cloud Resource Manager API enabled.
- A Desktop-type OAuth client. Download its JSON file.
- A Google account that owns or manages the Search Console properties you want to read.

## Build

```sh
git clone https://github.com/thefiredev-cloud/kodros-search-console-mcp.git
cd kodros-search-console-mcp
uv sync
```

`uv sync` installs the pinned dependencies from `uv.lock` (FastMCP 3, google-api-python-client, google-auth-oauthlib).

## Sign in once

```sh
uv run python authorize.py --client-secret /path/to/client_secret.json --expected-email you@example.com
```

The script opens a loopback listener on a random port and sends you to Google. It ignores any callback without the OAuth `state` value. It saves a token only when the ID token carries a verified email, and with `--expected-email` only when that email matches. The token file has mode 0600.

After you rotate the client secret in Google Cloud, run `uv run python set-client-secret.py`. It asks for the new secret with hidden input and rewrites the stored client JSON with mode 0600.

## Run

```sh
uv run python server.py
```

The server speaks MCP over stdio. Register it in a client as command `uv` with args `--directory /path/to/kodros-search-console-mcp run python server.py`.

## Settings

| Variable | Meaning | Default |
| --- | --- | --- |
| `GOOGLE_API_MCP_TOKEN_FILE` | Saved token | under `~/.config/google-api-mcp/` |
| `GOOGLE_API_MCP_CLIENT_FILE` | OAuth client JSON | under `~/.config/google-api-mcp/` |
| `GOOGLE_API_MCP_ACCOUNT` | Required account email | unset |

## Tools

Eleven tools. Reads: list properties, search analytics by query, page, country, device or date, sitemap status, URL inspection, and Cloud project search and get. Writes: add or remove a property, submit or remove a sitemap. Each write needs `confirm_site_url` or `confirm_feedpath` to repeat the exact target.

## Test

```sh
uv sync
uv run pytest
```

The offline suite covers the property-containment checks for sitemap and inspection URLs. It needs no credentials and makes no network calls. On 2026-11-19 it ran 16 tests. Live API calls were not run in this repository.

## Troubleshooting

- The server cannot find credentials: run `authorize.py` first, or set the three variables above.
- Removing a property removes it from your Search Console account, not from your website.
