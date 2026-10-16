from datetime import datetime
import json
import os
import threading
import traceback
from config import get_config
from logger import log_event

def _append_worker(model: str, user_prompt: str, assistant_response: str, sources_used: str):
    """Internal worker that runs in a background thread to append rows to Google Sheets."""
    sa_json_raw = get_config("GOOGLE_SERVICE_ACCOUNT_JSON")
    sheet_id = get_config("TARGET_SHEET_ID")

    if not sa_json_raw or not sheet_id:
        log_event("Sheets logging skipped: GOOGLE_SERVICE_ACCOUNT_JSON or TARGET_SHEET_ID is not set.")
        return

    log_event(f"Sheets background logging initiated for sheet ID: {sheet_id}")

    try:
        # Resolve service account credentials (handles JSON string or file path)
        sa_data = None
        trimmed = sa_json_raw.strip()
        if trimmed.startswith("{"):
            sa_data = json.loads(trimmed)
        elif os.path.exists(trimmed):
            with open(trimmed, "r", encoding="utf-8") as f:
                sa_data = json.load(f)
        else:
            try:
                sa_data = json.loads(trimmed)
            except Exception:
                log_event("Sheets logging error: GOOGLE_SERVICE_ACCOUNT_JSON is neither valid JSON nor a valid file path.", level="warning")
                return

        import gspread
        gc = gspread.service_account_from_dict(sa_data)
        workbook = gc.open_by_key(sheet_id)
        worksheet = workbook.sheet1

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = [
            now_str,
            model,
            user_prompt,
            assistant_response[:2000],  # Bound length for clean cell storage
            sources_used or "None",
        ]

        worksheet.append_row(row)
        log_event(f"Sheets logging succeeded: conversation row appended to {sheet_id}.")

    except Exception as exc:
        full_err = traceback.format_exc()
        log_event(f"Sheets logging failed: {full_err}", level="error")

def log_conversation_async(model: str, user_prompt: str, assistant_response: str, sources_used: str = ""):
    """
    Non-blocking async dispatcher for Google Sheets logging.
    Runs in a detached daemon thread so it never blocks or delays user interaction.
    """
    t = threading.Thread(
        target=_append_worker,
        args=(model, user_prompt, assistant_response, sources_used),
        daemon=True,
    )
    t.start()
