"""Authorise the uploader against the channel, once, and report what answered.

Deliberately stops after reporting. An account can own several channels and
Google hands back whichever one is currently selected, so the refresh token is
only worth storing after a human has confirmed the name that came back is the
right channel. Storing first and checking later means uploading a finished
video to the wrong place.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLIENT_SECRET = ROOT / "client_secret.json"
TOKEN_PATH = ROOT / "youtube_token.json"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/youtube.readonly",
]


def main():
    if not CLIENT_SECRET.exists():
        raise SystemExit(f"no client secret at {CLIENT_SECRET}")

    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
    # access_type=offline and prompt=consent together are what make Google issue
    # a refresh token. Without the prompt, a repeat authorisation returns only an
    # access token and the stored credential expires within the hour.
    creds = flow.run_local_server(
        port=0, access_type="offline", prompt="consent",
        authorization_prompt_message="Opening the browser to authorise...",
        success_message="Authorised. You can close this tab and return to the terminal.")

    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
    response = youtube.channels().list(part="snippet,contentDetails,statistics",
                                       mine=True).execute()
    items = response.get("items", [])
    if not items:
        raise SystemExit("authorised, but the account owns no channel")

    print("\n" + "=" * 56)
    for ch in items:
        snip = ch["snippet"]
        stats = ch.get("statistics", {})
        print(f"  Channel title : {snip['title']}")
        print(f"  Channel ID    : {ch['id']}")
        print(f"  Handle        : {snip.get('customUrl', '(none)')}")
        print(f"  Created       : {snip.get('publishedAt', '?')[:10]}")
        print(f"  Videos        : {stats.get('videoCount', '?')}")
        print(f"  Subscribers   : {stats.get('subscriberCount', '?')}")
    print("=" * 56)

    TOKEN_PATH.write_text(json.dumps({
        "refresh_token": creds.refresh_token,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "token_uri": creds.token_uri,
        "scopes": list(creds.scopes or SCOPES),
    }, indent=2), encoding="utf-8")

    print(f"\nrefresh token written locally to {TOKEN_PATH.name} (gitignored).")
    print("NOT stored in GitHub Secrets yet - waiting for confirmation that the")
    print("channel above is the right one.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
