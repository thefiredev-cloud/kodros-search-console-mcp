"""Authorize this MCP for the Google API scopes it uses.

The OAuth client project must have the Search Console API and the Cloud
Resource Manager API enabled. This flow requests `webmasters` (Search Console
read and write), `cloud-platform.read-only` (broad Google Cloud read access),
and `openid`/`userinfo.email` to verify the signed-in account. Pass
`--expected-email` (or set GOOGLE_API_MCP_ACCOUNT) to require a specific
account; without it any verified Google account is accepted. The MCP exposes
only Search Console property and sitemap writes and Cloud Resource Manager
project reads.
"""
from __future__ import annotations

import argparse
import os
import random
import time
import urllib.parse
import webbrowser
import wsgiref.simple_server
import wsgiref.util
from pathlib import Path
from typing import Any
from wsgiref.types import StartResponse, WSGIEnvironment

from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request
from google.oauth2 import id_token
from google_auth_oauthlib.flow import InstalledAppFlow

from server import CLIENT_FILE, OAUTH_SCOPES, TOKEN_FILE, save_credentials

CALLBACK_TIMEOUT_SECONDS = 1200


class _QuietHandler(wsgiref.simple_server.WSGIRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # keep the callback URL out of stderr
        pass


def _wait_for_callback(port: int, state: str) -> str:
    """Return the redirect URI carrying ``state``; answer anything else with 404.

    Local tools often probe listening ports with ``HEAD /`` every few seconds.
    google_auth_oauthlib's run_local_server accepts the first request it sees,
    so a probe ended the flow with MismatchingStateError before sign-in
    finished.
    """
    callback: list[str] = []

    def app(environ: WSGIEnvironment, start_response: StartResponse) -> list[bytes]:
        query = urllib.parse.parse_qs(environ.get("QUERY_STRING", ""))
        if query.get("state", [None])[0] != state:
            start_response("404 Not Found", [("Content-type", "text/plain")])
            return [b"Not the OAuth callback."]
        callback.append(wsgiref.util.request_uri(environ))
        start_response("200 OK", [("Content-type", "text/plain; charset=utf-8")])
        return [b"Google authorization received. You can close this tab."]

    server = wsgiref.simple_server.make_server(
        "127.0.0.1", port, app, handler_class=_QuietHandler
    )
    deadline = time.monotonic() + CALLBACK_TIMEOUT_SECONDS
    try:
        while not callback:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SystemExit("Timed out waiting for Google. No credentials were saved.")
            server.timeout = remaining
            server.handle_request()
    finally:
        server.server_close()
    return callback[0]




def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--client-secret",
        type=Path,
        default=CLIENT_FILE,
        help="Desktop OAuth client JSON path (default: %(default)s)",
    )
    parser.add_argument(
        "--expected-email",
        default=os.environ.get("GOOGLE_API_MCP_ACCOUNT") or None,
        help=(
            "Require this Google account for the token. Optional: when unset, "
            "any verified account is accepted "
            "(default: $GOOGLE_API_MCP_ACCOUNT, else unset)"
        ),
    )
    args = parser.parse_args()
    client_file = args.client_secret.expanduser()
    if not client_file.is_file():
        raise SystemExit(
            f"OAuth client file not found: {client_file}. Download a Desktop OAuth "
            "client JSON from the selected Google Cloud project."
        )

    flow = InstalledAppFlow.from_client_secrets_file(
        str(client_file), scopes=list(OAUTH_SCOPES)
    )
    callback_port = random.randint(49152, 65535)
    flow.redirect_uri = f"http://127.0.0.1:{callback_port}/"
    auth_kwargs = {"access_type": "offline", "prompt": "consent"}
    if args.expected_email:
        auth_kwargs["login_hint"] = args.expected_email
    auth_url, state = flow.authorization_url(**auth_kwargs)
    url_file = TOKEN_FILE.parent / "last_auth_url.txt"
    url_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    url_file.write_text(auth_url, encoding="utf-8")
    print(f"Open this URL to authorize your Google account:\n{auth_url}", flush=True)
    webbrowser.open(auth_url, new=1, autoraise=True)
    callback_uri = _wait_for_callback(callback_port, state)
    # oauthlib requires https for the authorization response; the listener is loopback-only.
    flow.fetch_token(authorization_response=callback_uri.replace("http://", "https://", 1))
    credentials = flow.credentials
    if not credentials.id_token:
        raise SystemExit(
            "Google did not return an identity token. No credentials were saved."
        )
    try:
        claims = id_token.verify_oauth2_token(
            credentials.id_token,
            Request(),
            credentials.client_id,
        )
    except (GoogleAuthError, ValueError):
        raise SystemExit(
            "Could not verify the Google account identity. No credentials were saved."
        ) from None

    email = claims.get("email", "")
    if claims.get("email_verified") is not True:
        raise SystemExit(
            "Google did not report a verified email for this account. No credentials were saved."
        )
    if args.expected_email and email.casefold() != args.expected_email.casefold():
        raise SystemExit(
            f"Expected a verified {args.expected_email} account but got {email}. "
            "No credentials were saved. If you authorized the wrong Google account, "
            "revoke that app grant in Google Account settings."
        )

    save_credentials(credentials)
    print(f"Authorized {email}; credentials saved to {TOKEN_FILE}.")


if __name__ == "__main__":
    main()
