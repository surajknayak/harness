import os
import re
from dotenv import load_dotenv

load_dotenv()

CONFIG_KEYS = [
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "XAI_API_KEY",
    "TAVILY_API_KEY",
    "GMAIL_USER",
    "GMAIL_APP_PASSWORD",
    "GOOGLE_SERVICE_ACCOUNT_JSON",
    "TARGET_SHEET_ID",
]

def sanitize_value(key: str, value: str | None) -> str:
    if not value:
        return ""
    # Strip non-ASCII and non-breaking spaces (\xa0 / \u00a0)
    cleaned = value.replace("\xa0", " ").replace("\u00a0", " ").strip()
    if key in ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "XAI_API_KEY", "TAVILY_API_KEY"]:
        cleaned = re.sub(r"[^\x20-\x7E]", "", cleaned).strip()
    elif key == "GMAIL_APP_PASSWORD":
        cleaned = re.sub(r"[^a-zA-Z0-9]", "", cleaned)
    return cleaned

def get_config(key: str) -> str:
    # First check Streamlit session_state if streamlit is imported and running
    val = ""
    try:
        import streamlit as st
        # Check custom session credentials dict if present
        if "session_creds" in st.session_state and key in st.session_state["session_creds"]:
            val = st.session_state["session_creds"][key]
        elif key in st.session_state:
            val = st.session_state[key]
    except Exception:
        pass

    if not val:
        val = os.environ.get(key, "")

    return sanitize_value(key, str(val) if val is not None else "")

def sync_config(key: str, value: str):
    cleaned = sanitize_value(key, value)
    # Sync to os.environ so runtime modules and fallbacks always see it
    if cleaned:
        os.environ[key] = cleaned
    else:
        os.environ.pop(key, None)

    try:
        import streamlit as st
        if "session_creds" not in st.session_state:
            st.session_state["session_creds"] = {}
        st.session_state["session_creds"][key] = cleaned
    except Exception:
        pass

def is_config_set(key: str) -> bool:
    return bool(get_config(key).strip())
