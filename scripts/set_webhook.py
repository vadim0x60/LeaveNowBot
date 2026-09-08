#!/usr/bin/env python3
import argparse
import json
import subprocess
import urllib.parse
import urllib.request


def secret(project: str, name: str) -> str:
    return subprocess.run(
        [
            "gcloud",
            "secrets",
            "versions",
            "access",
            "latest",
            f"--project={project}",
            f"--secret={name}",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Register the Cloud Run Telegram webhook.")
    parser.add_argument("--project", required=True)
    parser.add_argument("--service-url", required=True)
    args = parser.parse_args()

    token = secret(args.project, "leavenowbot-telegram-token")
    webhook_secret = secret(args.project, "leavenowbot-webhook-secret")
    if not webhook_secret:
        raise SystemExit("The webhook secret has no value.")
    data = urllib.parse.urlencode(
        {
            "url": args.service_url.rstrip("/") + "/telegram",
            "secret_token": webhook_secret,
            "allowed_updates": json.dumps(["message", "edited_message"]),
            "drop_pending_updates": "false",
        }
    ).encode()
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/setWebhook",
        data=data,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.load(response)
    if not result.get("ok"):
        raise SystemExit("Telegram rejected the webhook registration.")
    print("Telegram webhook registered.")


if __name__ == "__main__":
    main()
