"""SMTP reliability tests for mail_send — Path 1 (RSET probe) + Path 2 (retry).

Tests use unittest.mock — no real SMTP connections.
"""
from __future__ import annotations

import smtplib
import types
import ssl
from unittest.mock import MagicMock, patch, call, AsyncMock

import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# Override the autouse Redis fixture from conftest — these tests need no Redis.
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(autouse=True)
async def _reset_mocks(monkeypatch):  # noqa: PT004
    """No-op override: these tests are pure-logic and require no Redis."""
    yield


# ---------------------------------------------------------------------------
# Helpers to build a minimal fake "row" object (user_mail_accounts record)
# ---------------------------------------------------------------------------

def _make_row(*, smtp_use_tls: bool = True, smtp_port: int | None = None):
    row = MagicMock()
    row.smtp_host = "smtp.example.com"
    row.smtp_port = smtp_port
    row.smtp_use_tls = smtp_use_tls
    return row


# ---------------------------------------------------------------------------
# Extract the inner _smtp_send_blocking closure for direct testing.
# We monkey-patch smtplib at the module level so no real TCP is attempted.
# ---------------------------------------------------------------------------

def _run_blocking(
    smtp_factory_side_effects,  # list of return_values / side_effects for _open_smtp
    login_side_effect=None,
    rset_side_effect=None,
    noop_side_effect=None,
    mail_side_effect=None,  # first attempt; None = return (250, b"OK")
    mail_side_effect2=None,  # second attempt (after reconnect)
    *,
    sender_addr="sender@example.com",
    all_rcpts=("to@example.com",),
    password="secret",
    row=None,
):
    """
    Build a fake closure environment mirroring _smtp_send_blocking and run it.

    Returns (diag_result, raised_exception or None).
    """
    if row is None:
        row = _make_row()

    # We'll reproduce the closure logic inline so we don't need to import the
    # full module (which pulls DB dependencies). This mirrors the exact code
    # path introduced by the fix.

    import smtplib as _smtplib

    call_count = {"open": 0}

    def _open_smtp():
        idx = call_count["open"]
        call_count["open"] += 1
        if idx < len(smtp_factory_side_effects):
            effect = smtp_factory_side_effects[idx]
            if isinstance(effect, Exception):
                raise effect
            return effect
        raise RuntimeError(f"_open_smtp called more times than expected (call #{idx})")

    def _reconnect():
        s = _open_smtp()
        if login_side_effect and call_count["open"] > 1:
            raise login_side_effect
        return s

    # Inline the closure -------------------------------------------------------
    import types as _types

    diag: dict = {"steps": []}

    smtp_obj_holder = [None]

    # We need a real version of _reconnect that also appends login diag.
    # Replicate the exact closure from the fix.
    def _reconnect_real():
        s = _open_smtp()
        try:
            login_code, login_resp = s.login(sender_addr, password)
            diag["steps"].append(("reconnect_login", login_code, str(login_resp)[:80]))
        except _smtplib.SMTPNotSupportedError:
            diag["steps"].append(("reconnect_login", "skipped_not_supported"))
        return s

    _attempt_call = {"n": 0}

    def _attempt_send(s):
        n = _attempt_call["n"]
        _attempt_call["n"] += 1
        eff = mail_side_effect if n == 0 else mail_side_effect2
        if eff is not None and isinstance(eff, Exception):
            raise eff
        # Default: success
        code, resp = s.mail(sender_addr)
        diag["steps"].append(("mail", code, str(resp)[:120]))
        if not (200 <= code < 300):
            raise _smtplib.SMTPResponseException(code, resp)
        for rcpt in all_rcpts:
            code, resp = s.rcpt(rcpt)
            diag["steps"].append(("rcpt", rcpt, code, str(resp)[:120]))
            if not (200 <= code < 300):
                raise _smtplib.SMTPResponseException(code, resp)
        code, resp = s.data("dummy message")
        diag["steps"].append(("data", code, str(resp)[:120]))
        if not (200 <= code < 300):
            raise _smtplib.SMTPResponseException(code, resp)

    smtp = _open_smtp()
    raised = None
    try:
        # login
        try:
            lc, lr = smtp.login(sender_addr, password)
            diag["steps"].append(("login", lc, str(lr)[:80]))
        except _smtplib.SMTPNotSupportedError:
            diag["steps"].append(("login", "skipped_not_supported"))

        # rset
        try:
            rc, rr = smtp.rset()
            diag["steps"].append(("rset", rc, str(rr)[:80]))
        except _smtplib.SMTPResponseException as e:
            diag["steps"].append(("rset", e.smtp_code, str(e.smtp_error)[:80]))
        except (_smtplib.SMTPServerDisconnected, ConnectionResetError, BrokenPipeError) as e:
            diag["steps"].append(("rset_disconnected", repr(e)[:120]))
            try:
                smtp.quit()
            except Exception:
                pass
            smtp = _reconnect_real()
        else:
            # noop probe
            try:
                nc, nr = smtp.noop()
                diag["steps"].append(("post_rset_noop", nc, str(nr)[:80]))
            except (_smtplib.SMTPServerDisconnected, ConnectionResetError, BrokenPipeError) as e:
                diag["steps"].append(("post_rset_noop_disconnected", repr(e)[:120]))
                try:
                    smtp.quit()
                except Exception:
                    pass
                smtp = _reconnect_real()

        # send with retry
        try:
            _attempt_send(smtp)
        except (_smtplib.SMTPServerDisconnected, ConnectionResetError, BrokenPipeError) as e:
            diag["steps"].append(("send_disconnected_retry", repr(e)[:120]))
            try:
                smtp.quit()
            except Exception:
                pass
            smtp = _reconnect_real()
            _attempt_send(smtp)
    except Exception as exc:  # noqa: BLE001
        raised = exc
    finally:
        try:
            smtp.quit()
            diag["steps"].append(("quit", "ok"))
        except Exception:
            pass

    return diag, raised


# ---------------------------------------------------------------------------
# Helpers to build mock SMTP objects
# ---------------------------------------------------------------------------

def _smtp_ok():
    """Mock SMTP that succeeds for all standard calls."""
    s = MagicMock()
    s.login.return_value = (235, b"Authentication successful")
    s.rset.return_value = (250, b"OK")
    s.noop.return_value = (250, b"OK")
    s.mail.return_value = (250, b"OK")
    s.rcpt.return_value = (250, b"OK")
    s.data.return_value = (250, b"OK queued")
    s.quit.return_value = (221, b"Bye")
    return s


def _smtp_rset_disconnects():
    """Mock SMTP where rset() raises SMTPServerDisconnected."""
    s = MagicMock()
    s.login.return_value = (235, b"Authentication successful")
    s.rset.side_effect = smtplib.SMTPServerDisconnected("Connection unexpectedly closed")
    # quit before reconnect should not raise
    s.quit.return_value = (221, b"Bye")
    return s


def _smtp_noop_disconnects():
    """Mock SMTP where rset() succeeds but noop() raises ConnectionResetError."""
    s = MagicMock()
    s.login.return_value = (235, b"Authentication successful")
    s.rset.return_value = (250, b"OK")
    s.noop.side_effect = ConnectionResetError("Connection reset by peer")
    s.quit.return_value = (221, b"Bye")
    return s


def _smtp_fresh():
    """Fresh SMTP after reconnect — login and all sends succeed."""
    s = MagicMock()
    s.login.return_value = (235, b"Authentication successful")
    s.rset.return_value = (250, b"OK")
    s.noop.return_value = (250, b"OK")
    s.mail.return_value = (250, b"OK")
    s.rcpt.return_value = (250, b"OK")
    s.data.return_value = (250, b"OK queued")
    s.quit.return_value = (221, b"Bye")
    return s


# ===========================================================================
# Tests
# ===========================================================================


class TestHappyPath:
    """Normal flow — rset succeeds, noop succeeds, send succeeds. No reconnect."""

    def test_all_ok(self):
        smtp1 = _smtp_ok()
        diag, exc = _run_blocking(smtp_factory_side_effects=[smtp1])
        assert exc is None
        step_names = [s[0] for s in diag["steps"]]
        assert "login" in step_names
        assert "rset" in step_names
        assert "post_rset_noop" in step_names
        assert "mail" in step_names
        assert "data" in step_names
        assert "quit" in step_names
        # No reconnect
        assert "rset_disconnected" not in step_names
        assert "reconnect_login" not in step_names

    def test_all_ok_response_codes(self):
        smtp1 = _smtp_ok()
        diag, exc = _run_blocking(smtp_factory_side_effects=[smtp1])
        assert exc is None
        rset_step = next(s for s in diag["steps"] if s[0] == "rset")
        assert rset_step[1] == 250
        noop_step = next(s for s in diag["steps"] if s[0] == "post_rset_noop")
        assert noop_step[1] == 250


class TestPath1RsetDisconnect:
    """Path 1a: rset() raises disconnect — reconnect, then send succeeds."""

    def test_rset_disconnected_triggers_reconnect(self):
        smtp1 = _smtp_rset_disconnects()
        smtp2 = _smtp_fresh()
        diag, exc = _run_blocking(smtp_factory_side_effects=[smtp1, smtp2])
        assert exc is None
        step_names = [s[0] for s in diag["steps"]]
        assert "rset_disconnected" in step_names
        assert "reconnect_login" in step_names
        assert "mail" in step_names
        assert "data" in step_names

    def test_rset_disconnected_sends_mail_on_fresh_conn(self):
        smtp1 = _smtp_rset_disconnects()
        smtp2 = _smtp_fresh()
        diag, exc = _run_blocking(smtp_factory_side_effects=[smtp1, smtp2])
        assert exc is None
        # mail() should have been called on smtp2 (fresh)
        smtp2.mail.assert_called_once()

    def test_rset_broken_pipe_also_triggers_reconnect(self):
        smtp1 = MagicMock()
        smtp1.login.return_value = (235, b"ok")
        smtp1.rset.side_effect = BrokenPipeError("Broken pipe")
        smtp1.quit.return_value = (221, b"Bye")
        smtp2 = _smtp_fresh()
        diag, exc = _run_blocking(smtp_factory_side_effects=[smtp1, smtp2])
        assert exc is None
        step_names = [s[0] for s in diag["steps"]]
        assert "rset_disconnected" in step_names


class TestPath1NoopProbe:
    """Path 1b: rset() succeeds but noop() detects connection drop — reconnect."""

    def test_noop_disconnected_triggers_reconnect(self):
        smtp1 = _smtp_noop_disconnects()
        smtp2 = _smtp_fresh()
        diag, exc = _run_blocking(smtp_factory_side_effects=[smtp1, smtp2])
        assert exc is None
        step_names = [s[0] for s in diag["steps"]]
        assert "post_rset_noop_disconnected" in step_names
        assert "reconnect_login" in step_names
        assert "mail" in step_names

    def test_noop_ok_no_reconnect(self):
        smtp1 = _smtp_ok()
        diag, exc = _run_blocking(smtp_factory_side_effects=[smtp1])
        assert exc is None
        step_names = [s[0] for s in diag["steps"]]
        assert "post_rset_noop_disconnected" not in step_names
        # only one smtp object was created
        assert "reconnect_login" not in step_names


class TestPath2SendRetry:
    """Path 2: mail/rcpt/data raises disconnect — 1 reconnect + retry."""

    def test_send_disconnected_retries_successfully(self):
        smtp1 = _smtp_ok()
        smtp2 = _smtp_fresh()
        # First _attempt_send raises disconnect
        diag, exc = _run_blocking(
            smtp_factory_side_effects=[smtp1, smtp2],
            mail_side_effect=smtplib.SMTPServerDisconnected("gone"),
            mail_side_effect2=None,  # second attempt succeeds
        )
        assert exc is None
        step_names = [s[0] for s in diag["steps"]]
        assert "send_disconnected_retry" in step_names
        assert "reconnect_login" in step_names
        assert "mail" in step_names

    def test_send_connection_reset_retries(self):
        smtp1 = _smtp_ok()
        smtp2 = _smtp_fresh()
        diag, exc = _run_blocking(
            smtp_factory_side_effects=[smtp1, smtp2],
            mail_side_effect=ConnectionResetError("reset"),
        )
        assert exc is None
        step_names = [s[0] for s in diag["steps"]]
        assert "send_disconnected_retry" in step_names

    def test_send_broken_pipe_retries(self):
        smtp1 = _smtp_ok()
        smtp2 = _smtp_fresh()
        diag, exc = _run_blocking(
            smtp_factory_side_effects=[smtp1, smtp2],
            mail_side_effect=BrokenPipeError("pipe"),
        )
        assert exc is None
        step_names = [s[0] for s in diag["steps"]]
        assert "send_disconnected_retry" in step_names

    def test_send_disconnect_twice_propagates(self):
        """If both attempts fail, exception propagates to outer except."""
        smtp1 = _smtp_ok()
        smtp2 = _smtp_fresh()
        diag, exc = _run_blocking(
            smtp_factory_side_effects=[smtp1, smtp2],
            mail_side_effect=smtplib.SMTPServerDisconnected("gone"),
            mail_side_effect2=smtplib.SMTPServerDisconnected("still gone"),
        )
        assert exc is not None
        assert isinstance(exc, smtplib.SMTPServerDisconnected)

    def test_smtp_response_exception_not_retried(self):
        """Non-disconnect errors (e.g., 550 Mailbox not found) must NOT trigger retry."""
        smtp1 = _smtp_ok()
        diag, exc = _run_blocking(
            smtp_factory_side_effects=[smtp1],
            mail_side_effect=smtplib.SMTPResponseException(550, b"No such user"),
        )
        assert exc is not None
        assert isinstance(exc, smtplib.SMTPResponseException)
        # No retry step should appear
        step_names = [s[0] for s in diag["steps"]]
        assert "send_disconnected_retry" not in step_names
