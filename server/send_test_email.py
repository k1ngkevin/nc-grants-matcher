"""Send a standalone Azure SDK test email using the repository-root .env.

Install: python -m pip install -r requirements-email-test.txt
Run:     python send_test_email.py --to vedhkris@gmail.com
This script sends real email only when run explicitly, not during pytest.
"""
import argparse
import os
from email.utils import parseaddr
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a test email with Azure Communication Services.")
    parser.add_argument("--to", required=True, help="Recipient email address")
    parser.add_argument("--sender", help="Verified Azure MailFrom address; defaults to SMTP_FROM in .env")
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv
        from azure.communication.email import EmailClient
        from azure.core.exceptions import AzureError
    except ImportError:
        parser.exit(2, "Install dependencies: python -m pip install -r requirements-email-test.txt\n")

    # Resolve from this script, so running from a different directory is safe.
    # Existing environment variables take precedence. docs/.env is not loaded.
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    connection_string = os.getenv("ACS_CONNECTION_STRING", "").strip()
    sender = parseaddr(args.sender or os.getenv("SMTP_FROM", ""))[1]
    recipient = args.to.strip()
    if not connection_string or "<your-" in connection_string:
        parser.exit(2, "Set ACS_CONNECTION_STRING in nc-grants-matcher/.env to your resource's real connection string.\n")
    if not sender or "@" not in sender or "example." in sender or "your-domain" in sender:
        parser.exit(2, "Set SMTP_FROM in the root .env (or --sender) to your verified Azure MailFrom address.\n")
    if "@" not in recipient or any(c in recipient for c in "\r\n"):
        parser.exit(2, "Provide a valid recipient with --to.\n")

    message = {
        "senderAddress": sender,
        "recipients": {"to": [{"address": recipient}]},
        "content": {
            "subject": "NC Grant Alert Test Dispatch",
            "plainText": "This is a test notification from your Azure Communication Services resource!",
        },
    }
    try:
        with EmailClient.from_connection_string(connection_string) as client:
            poller = client.begin_send(message)
            result = poller.result(timeout=120)
    except AzureError as exc:
        # Report only structured diagnostics, never raw messages or request headers.
        print(f"Azure email error: {type(exc).__name__}")
        status = getattr(exc, "status_code", None)
        if isinstance(status, int):
            print(f"HTTP status: {status}")
        code = getattr(getattr(exc, "error", None), "code", None)
        if isinstance(code, str) and code.replace("_", "").replace("-", "").isalnum():
            print(f"Azure error code: {code}")
        print("Check the connection string, linked domain, MailFrom address, and Azure email logs.")
        return 1
    except (ValueError, TimeoutError) as exc:
        print(f"Email configuration or timeout error: {type(exc).__name__}. Check the connection string and Azure email logs.")
        return 1
    print(f"Email send status: {result.get('status', 'Unknown')}")
    print(f"Operation ID: {result.get('id', 'not returned')}")
    return 0 if result.get("status") == "Succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
