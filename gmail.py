import email
from email.header import decode_header
import imaplib
import re
from config import get_config
from logger import log_event

# 10 MB buffer to prevent large inbox overflows
imaplib._MAXLINE = 10_000_000

def _clean_header_value(val: str | None) -> str:
    if not val:
        return "Unknown"
    decoded_parts = decode_header(val)
    out = []
    for content, encoding in decoded_parts:
        if isinstance(content, bytes):
            out.append(content.decode(encoding or "utf-8", errors="replace"))
        else:
            out.append(str(content))
    return "".join(out).strip()

def _extract_body(msg) -> str:
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            cdispo = str(part.get("Content-Disposition"))
            if ctype == "text/plain" and "attachment" not in cdispo:
                payload = part.get_payload(decode=True)
                if payload:
                    body = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                    break
        if not body:
            # Fallback to text/html if no plain text
            for part in msg.walk():
                ctype = part.get_content_type()
                if ctype == "text/html":
                    payload = part.get_payload(decode=True)
                    if payload:
                        raw = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                        # Basic html tag stripping
                        body = re.sub(r"<[^>]+>", " ", raw)
                        break
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            body = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")

    # Clean whitespace and truncate ~1000 chars
    body = re.sub(r"\s+", " ", body).strip()
    if len(body) > 1000:
        body = body[:1000] + "… [truncated]"
    return body or "[No text body]"

def get_recent_emails() -> dict:
    """
    Fetches the 10 most recent emails from Gmail via read-only IMAP.
    Follows all safety rules:
    - Sanitizes app password (16 alphanumerics, strips spaces and \\xa0)
    - 10MB _MAXLINE buffer
    - Never uses SEARCH ALL
    - Uses BODY.PEEK[] so messages are never marked read
    - Traps login exceptions without UI tracebacks
    - Logs complete IMAP exchange to console and harness.log
    """
    user = get_config("GMAIL_USER")
    raw_pass = get_config("GMAIL_APP_PASSWORD")

    if not user or not raw_pass:
        msg = "Gmail credentials missing: Please provide GMAIL_USER and GMAIL_APP_PASSWORD in Settings."
        log_event(f"Gmail fetch aborted: {msg}", level="warning")
        return {"messages": [], "error": msg, "count": 0}

    # Strict password sanitization per spec
    sanitized_pass = re.sub(r"[^a-zA-Z0-9]", "", raw_pass)
    if len(sanitized_pass) != 16:
        log_event(f"Gmail app password length is {len(sanitized_pass)} (expected 16 alphanumerics).", level="warning")

    imap_host = "imap.gmail.com"
    imap_port = 993
    log_event(f"Initiating IMAP connection to {imap_host}:{imap_port} for user: {user}")

    mail = None
    try:
        mail = imaplib.IMAP4_SSL(imap_host, imap_port)
        log_event("IMAP4_SSL connection established successfully.")

        try:
            mail.login(user, sanitized_pass)
            log_event(f"IMAP login succeeded for user '{user}'.")
        except Exception as login_err:
            err_str = str(login_err)
            log_event(f"IMAP login failed: {repr(login_err)}", level="error")
            return {
                "messages": [],
                "error": f"⚠️ Gmail Diagnostic: Login failed ({err_str}). Verify email and 16-char App Password.",
                "count": 0,
            }

        # Select INBOX in read-only mode
        status, data = mail.select("INBOX", readonly=True)
        total = 0
        if status == "OK" and data and data[0]:
            try:
                total = int(data[0].decode())
            except Exception:
                total = 0
        log_event(f"IMAP select INBOX status: {status}, total messages: {total}")

        # Fallback to '[Gmail]/All Mail' if INBOX total is 0
        if total == 0:
            log_event("INBOX empty or 0 messages; trying '[Gmail]/All Mail' fallback.")
            status_all, data_all = mail.select('"[Gmail]/All Mail"', readonly=True)
            if status_all == "OK" and data_all and data_all[0]:
                try:
                    total = int(data_all[0].decode())
                except Exception:
                    total = 0
            log_event(f"IMAP select [Gmail]/All Mail status: {status_all}, total: {total}")

        # If still 0, cleanly return no messages
        if total == 0:
            log_event("No messages found in mailbox.")
            return {"messages": [], "error": None, "count": 0}

        # Compute range: max(1, total - 9) to total (last 10 emails)
        start = max(1, total - 9)
        end = total
        log_event(f"Fetching recent sequence range {start}:{end} (total: {total})")

        # Fetch using BODY.PEEK[] so messages remain unread
        fetch_range = f"{start}:{end}"
        fetch_status, fetch_data = mail.fetch(fetch_range, "(BODY.PEEK[])")
        if fetch_status != "OK" or not fetch_data:
            err_msg = f"Failed to fetch sequence range {fetch_range}: status {fetch_status}"
            log_event(err_msg, level="error")
            return {"messages": [], "error": f"⚠️ Gmail Diagnostic: {err_msg}", "count": 0}

        emails = []
        for response_part in reversed(fetch_data):
            if isinstance(response_part, tuple) and len(response_part) >= 2:
                raw_bytes = response_part[1]
                msg = email.message_from_bytes(raw_bytes)
                
                subj = _clean_header_value(msg.get("Subject"))
                sender = _clean_header_value(msg.get("From"))
                date_str = _clean_header_value(msg.get("Date"))
                body_text = _extract_body(msg)

                emails.append({
                    "subject": subj,
                    "from": sender,
                    "date": date_str,
                    "body": body_text,
                })

        log_event(f"Successfully retrieved and parsed {len(emails)} recent emails.")
        return {"messages": emails, "error": None, "count": len(emails)}

    except Exception as exc:
        full_err = f"IMAP exchange failure: {repr(exc)}"
        log_event(full_err, level="error")
        return {"messages": [], "error": f"⚠️ Gmail Diagnostic: {str(exc)}", "count": 0}

    finally:
        if mail:
            try:
                mail.close()
            except Exception:
                pass
            try:
                mail.logout()
            except Exception:
                pass

def format_emails_for_prompt(emails: list) -> str:
    """Formats retrieved emails into prompt grounding context."""
    if not emails:
        return ""
    lines = ["=== RECENT GMAIL INBOX (READ-ONLY GROUNDING CONTEXT) ==="]
    for i, em in enumerate(emails, 1):
        lines.append(f"\n[Email #{i}]")
        lines.append(f"From: {em['from']}")
        lines.append(f"Date: {em['date']}")
        lines.append(f"Subject: {em['subject']}")
        lines.append(f"Body: {em['body']}")
    lines.append("\n=== END GMAIL CONTEXT ===")
    return "\n".join(lines)
