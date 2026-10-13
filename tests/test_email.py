"""Account email flows use a stub transport; no email leaves the test process."""

from contextlib import closing
import json
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError
from uuid import uuid4

from werkzeug.security import generate_password_hash

from app import APP_DIR, create_app
from db import connect, migrate
from email_delivery import EmailDeliveryError, send_email


PASSWORD = "StrongPassword123"


class EmailAccountTests(unittest.TestCase):
    def setUp(self):
        self.path = APP_DIR / f".test-email-{uuid4().hex}.sqlite3"
        self.addCleanup(lambda: self.path.unlink(missing_ok=True))
        migrate(self.path)
        self.app = create_app({
            "TESTING": True, "SECRET_KEY": "test-secret-key-of-at-least-32-characters",
            "DATABASE": str(self.path), "EMAIL_ENABLED": True, "EMAIL_PROVIDER": "brevo",
            "EMAIL_API_KEY": "test-key", "EMAIL_FROM": "sender@example.com",
            "PUBLIC_BASE_URL": "https://tracker.example.com",
        })
        self.client = self.app.test_client()
        self.outbox = []
        sender = patch("app.send_account_email", side_effect=lambda *args: self.outbox.append(args))
        sender.start()
        self.addCleanup(sender.stop)

    def csrf(self):
        self.client.get("/login")
        with self.client.session_transaction() as session:
            return session["csrf_token"]

    def last_link(self):
        return self.outbox[-1][-1].splitlines()[-1].replace("https://tracker.example.com", "")

    def register(self, name="alice", email="alice@example.com"):
        return self.client.post("/register", data={"csrf_token": self.csrf(),
            "username": name, "email": email, "password": PASSWORD})

    def test_signup_requires_verified_email_and_one_use_token(self):
        self.assertEqual(self.register().status_code, 302)
        self.assertEqual(len(self.outbox), 1)
        self.assertEqual(self.client.post("/login", data={"csrf_token": self.csrf(),
            "username": "alice", "password": PASSWORD}).status_code, 403)
        link = self.last_link()
        self.assertEqual(self.client.get(link).status_code, 200)
        self.assertEqual(self.client.post(link).status_code, 400)
        self.assertEqual(self.client.post(link, data={"csrf_token": self.csrf()}).status_code, 302)
        self.assertEqual(self.client.get(link).status_code, 400)
        with closing(connect(self.path)) as db:
            row = db.execute("SELECT email,email_verified_at FROM users WHERE username='alice'").fetchone()
            self.assertEqual(row["email"], "alice@example.com")
            self.assertIsNotNone(row["email_verified_at"])
        self.assertEqual(self.client.post("/login", data={"csrf_token": self.csrf(),
            "username": "alice", "password": PASSWORD}).status_code, 302)

    def test_resend_replaces_token_and_reset_is_single_use(self):
        self.register()
        old = self.last_link()
        self.assertEqual(self.client.post("/verify-email/resend", data={"csrf_token": self.csrf(),
            "email": "alice@example.com"}).status_code, 302)
        self.assertEqual(self.client.get(old).status_code, 400)
        self.client.post(self.last_link(), data={"csrf_token": self.csrf()})
        self.outbox.clear()
        self.assertEqual(self.client.post("/forgot-password", data={"csrf_token": self.csrf(),
            "email": "missing@example.com"}).status_code, 302)
        self.assertFalse(self.outbox)
        self.assertEqual(self.client.post("/forgot-password", data={"csrf_token": self.csrf(),
            "email": "alice@example.com"}).status_code, 302)
        link = self.last_link()
        self.assertEqual(self.client.post(link, data={"csrf_token": self.csrf(),
            "new_password": "AnotherPassword789", "confirm_password": "AnotherPassword789"}).status_code, 302)
        self.assertEqual(self.client.get(link).status_code, 400)
        self.assertEqual(self.client.post("/login", data={"csrf_token": self.csrf(),
            "username": "alice", "password": "AnotherPassword789"}).status_code, 302)

    def test_existing_account_can_verify_recovery_email(self):
        with closing(connect(self.path)) as db:
            db.execute("INSERT INTO users(username,password) VALUES (?,?)",
                       ("legacy", generate_password_hash(PASSWORD)))
            db.commit()
        self.assertEqual(self.client.post("/login", data={"csrf_token": self.csrf(),
            "username": "legacy", "password": PASSWORD}).status_code, 302)
        self.assertEqual(self.client.post("/settings/email", data={"csrf_token": self.csrf(),
            "email": "legacy@example.com", "current_password": "wrong"}).status_code, 400)
        self.assertEqual(self.client.post("/settings/email", data={"csrf_token": self.csrf(),
            "email": "legacy@example.com", "current_password": PASSWORD}).status_code, 302)
        with closing(connect(self.path)) as db:
            self.assertIsNone(db.execute("SELECT email FROM users WHERE username='legacy'").fetchone()[0])
        self.assertEqual(self.client.post(self.last_link(), data={"csrf_token": self.csrf()}).status_code, 302)
        with closing(connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT email FROM users WHERE username='legacy'").fetchone()[0],
                             "legacy@example.com")

    def test_signup_and_reset_rate_limits(self):
        for n in range(5):
            self.assertEqual(self.register(f"user{n}", f"user{n}@example.com").status_code, 302)
        self.assertEqual(self.register("user5", "user5@example.com").status_code, 429)
        for n in range(5):
            self.assertEqual(self.client.post("/forgot-password", data={"csrf_token": self.csrf(),
                "email": f"missing{n}@example.com"}).status_code, 302)
        self.assertEqual(self.client.post("/forgot-password", data={"csrf_token": self.csrf(),
            "email": "last@example.com"}).status_code, 429)


class EmailDeliveryTests(unittest.TestCase):
    def test_https_provider_request_and_rejected_response(self):
        response = MagicMock()
        response.status = 201
        response.__enter__.return_value = response
        with patch("email_delivery.urlopen", return_value=response) as opener:
            send_email("brevo", "private-key", "sender@example.com", "user@example.com",
                       "Verify", "Message")
        request = opener.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.brevo.com/v3/smtp/email")
        self.assertEqual(request.get_header("Api-key"), "private-key")
        self.assertEqual(json.loads(request.data)["to"][0]["email"], "user@example.com")
        with patch("email_delivery.urlopen", side_effect=HTTPError(
                "https://api.brevo.com/v3/smtp/email", 403, "Denied", {}, None)):
            with self.assertRaises(EmailDeliveryError):
                send_email("brevo", "private-key", "sender@example.com", "user@example.com",
                           "Verify", "Message")


if __name__ == "__main__":
    unittest.main()
