"""Transactional email over HTTPS for PythonAnywhere's free-account proxy."""

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class EmailDeliveryError(RuntimeError):
    pass


def send_email(provider, api_key, sender, recipient, subject, body):
    if provider == "brevo":
        url = "https://api.brevo.com/v3/smtp/email"
        headers = {"api-key": api_key}
        payload = {"sender": {"name": "Expense Tracker", "email": sender},
                   "to": [{"email": recipient}], "subject": subject, "textContent": body}
    elif provider == "resend":
        url = "https://api.resend.com/emails"
        headers = {"Authorization": f"Bearer {api_key}"}
        payload = {"from": sender, "to": [recipient], "subject": subject, "text": body}
    else:
        raise ValueError("Unsupported email provider")
    request = Request(url, data=json.dumps(payload).encode("utf-8"), method="POST",
                      headers={"Content-Type": "application/json", **headers})
    try:
        with urlopen(request, timeout=10) as response:
            if response.status not in (200, 201, 202):
                raise EmailDeliveryError("Email provider did not accept the message")
    except (HTTPError, URLError, TimeoutError) as exc:
        # Provider error bodies can contain addresses or links; never log them.
        raise EmailDeliveryError("Email provider did not accept the message") from exc
