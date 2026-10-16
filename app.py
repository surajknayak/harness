import streamlit as st
from config import CONFIG_KEYS, get_config, sync_config, is_config_set
from logger import log_event
from llm import ask
from rag import extract_text_from_file
from sheets import log_conversation_async

# ---------------------------------------------------------
# Page Configuration & Visual Theme
# ---------------------------------------------------------
if "harness_title" not in st.session_state:
    st.session_state["harness_title"] = "The Harness"

st.set_page_config(
    page_title=st.session_state["harness_title"],
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Minimalist high-end light theme styling
st.markdown(
    """
    <style>
    /* Global background and typography */
    .stApp {
        background-color: #FFFFFF;
        color: #0F172A;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }
    
    /* Subtle slate borders and cards */
    section[data-testid="stSidebar"] {
        background-color: #F8FAFC;
        border-right: 1px solid #E2E8F0;
    }
    
    /* Clean headers */
    h1, h2, h3 {
        color: #0F172A;
        font-weight: 600;
        letter-spacing: -0.02em;
    }
    
    /* Claude-style tool container */
    div.tool-row-container {
        background-color: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 10px;
        padding: 10px 14px;
        margin-top: 10px;
        margin-bottom: 8px;
    }
    
    /* Status indicators */
    .status-set {
        color: #10B981;
        font-size: 0.85rem;
        font-weight: 500;
    }
    .status-empty {
        color: #94A3B8;
        font-size: 0.85rem;
        font-weight: 500;
    }
    
    /* Streamlit widget refinements */
    div[data-testid="stFileUploader"] {
        padding: 0;
    }
    div[data-testid="stFileUploader"] section {
        padding: 6px 10px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------
# Session State Initialization
# ---------------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []

# ---------------------------------------------------------
# Right Zone: Settings Dialog
# ---------------------------------------------------------
@st.dialog("Settings", width="large")
def show_settings_dialog():
    st.markdown("Configure harness preferences and active credentials for this session.")
    
    # 1. Harness Title
    new_title = st.text_input(
        "Harness Title",
        value=st.session_state.get("harness_title", "The Harness"),
        help="Updates the sidebar name live across the application.",
    )
    
    st.markdown("---")
    
    # Status badges helper
    def render_field_status(key: str, label: str):
        is_set = is_config_set(key)
        icon = "●" if is_set else "○"
        status_text = "set" if is_set else "empty"
        color_class = "status-set" if is_set else "status-empty"
        return f"{label} <span class='{color_class}'>{icon} {status_text}</span>"

    # 2. Models & Web
    st.subheader("Models · Web")
    col_m1, col_m2 = st.columns(2)
    with col_m1:
        st.markdown(render_field_status("ANTHROPIC_API_KEY", "Anthropic API Key"), unsafe_allow_html=True)
        anthropic_val = st.text_input(
            "Anthropic API Key",
            type="password",
            placeholder="sk-ant-...",
            label_visibility="collapsed",
            key="input_anthropic",
        )
        
        st.markdown(render_field_status("OPENAI_API_KEY", "OpenAI API Key"), unsafe_allow_html=True)
        openai_val = st.text_input(
            "OpenAI API Key",
            type="password",
            placeholder="sk-...",
            label_visibility="collapsed",
            key="input_openai",
        )

    with col_m2:
        st.markdown(render_field_status("XAI_API_KEY", "xAI API Key (Grok)"), unsafe_allow_html=True)
        xai_val = st.text_input(
            "xAI API Key",
            type="password",
            placeholder="xai-...",
            label_visibility="collapsed",
            key="input_xai",
        )
        
        st.markdown(render_field_status("TAVILY_API_KEY", "Tavily API Key"), unsafe_allow_html=True)
        tavily_val = st.text_input(
            "Tavily API Key",
            type="password",
            placeholder="tvly-...",
            label_visibility="collapsed",
            key="input_tavily",
        )

    st.markdown("---")

    # 3. Email
    st.subheader("Email (Gmail IMAP)")
    col_e1, col_e2 = st.columns(2)
    with col_e1:
        st.markdown(render_field_status("GMAIL_USER", "Gmail Address"), unsafe_allow_html=True)
        gmail_user_val = st.text_input(
            "Gmail Address",
            placeholder="user@gmail.com",
            label_visibility="collapsed",
            key="input_gmail_user",
        )
    with col_e2:
        st.markdown(render_field_status("GMAIL_APP_PASSWORD", "Gmail App Password (16-char)"), unsafe_allow_html=True)
        gmail_pass_val = st.text_input(
            "Gmail App Password",
            type="password",
            placeholder="abcd efgh ijkl mnop",
            label_visibility="collapsed",
            key="input_gmail_pass",
        )

    st.markdown("---")

    # 4. Sheets
    st.subheader("Google Sheets (Logging)")
    col_s1, col_s2 = st.columns([1.2, 0.8])
    with col_s1:
        st.markdown(render_field_status("GOOGLE_SERVICE_ACCOUNT_JSON", "Service Account JSON"), unsafe_allow_html=True)
        service_account_val = st.text_area(
            "Google Service Account JSON",
            placeholder='{"type": "service_account", ...}',
            height=100,
            label_visibility="collapsed",
            key="input_service_account",
        )
    with col_s2:
        st.markdown(render_field_status("TARGET_SHEET_ID", "Target Sheet ID"), unsafe_allow_html=True)
        sheet_id_val = st.text_input(
            "Target Sheet ID",
            placeholder="1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms",
            label_visibility="collapsed",
            key="input_sheet_id",
        )

    st.markdown("")
    if st.button("Save for this session", type="primary", use_container_width=True):
        # Update title
        if new_title.strip():
            st.session_state["harness_title"] = new_title.strip()
        
        # Sync non-empty credentials
        creds_to_save = {
            "ANTHROPIC_API_KEY": anthropic_val,
            "OPENAI_API_KEY": openai_val,
            "XAI_API_KEY": xai_val,
            "TAVILY_API_KEY": tavily_val,
            "GMAIL_USER": gmail_user_val,
            "GMAIL_APP_PASSWORD": gmail_pass_val,
            "GOOGLE_SERVICE_ACCOUNT_JSON": service_account_val,
            "TARGET_SHEET_ID": sheet_id_val,
        }
        for k, v in creds_to_save.items():
            if v and v.strip():
                sync_config(k, v)
        
        log_event(f"Settings saved for session. Title: '{st.session_state['harness_title']}'")
        st.rerun()

# ---------------------------------------------------------
# Left Zone: Native Sidebar
# ---------------------------------------------------------
with st.sidebar:
    st.title(st.session_state["harness_title"])
    st.caption("Grounded Multi-Model AI Orchestrator")
    
    st.markdown(
        """
        ### How it works
        1. **Pick a model** — choose between Claude, OpenAI, or Grok.
        2. **Toggle capabilities** — enable Web, Docs, or Email.
        3. **Ask anything** — the model grounds answers in real sources and cites what fired.
        """
    )
    
    st.divider()
    
    # Active status summary
    st.markdown("**Session Status**")
    m_ok = any(is_config_set(k) for k in ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "XAI_API_KEY"])
    w_ok = is_config_set("TAVILY_API_KEY")
    e_ok = is_config_set("GMAIL_USER") and is_config_set("GMAIL_APP_PASSWORD")
    s_ok = is_config_set("GOOGLE_SERVICE_ACCOUNT_JSON") and is_config_set("TARGET_SHEET_ID")
    
    st.write(f"• LLM Provider: {'🟢 Ready' if m_ok else '⚪ Key not set'}")
    st.write(f"• Web Search: {'🟢 Ready' if w_ok else '⚪ Tavily not set'}")
    st.write(f"• Gmail IMAP: {'🟢 Ready' if e_ok else '⚪ Not configured'}")
    st.write(f"• Sheets Log: {'🟢 Ready' if s_ok else '⚪ Optional / Idle'}")

# ---------------------------------------------------------
# Center Zone: Main Chat Area
# ---------------------------------------------------------
# Top bar with Settings trigger
top_col1, top_col2 = st.columns([0.85, 0.15])
with top_col1:
    st.subheader(st.session_state["harness_title"])
with top_col2:
    if st.button("⚙️ Settings", use_container_width=True):
        show_settings_dialog()

# Chat message feed
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Claude-style composer tool row directly above prompt input
with st.container():
    st.markdown('<div class="tool-row-container">', unsafe_allow_html=True)
    c_model, c_web, c_mail, c_docs, c_upload = st.columns([1.8, 0.9, 0.9, 0.9, 2.5], vertical_alignment="center")
    
    with c_model:
        selected_model = st.selectbox(
            "Model",
            ["Claude (claude-sonnet-4-6)", "OpenAI (gpt-4o)", "Grok (grok-2-latest)"],
            label_visibility="collapsed",
            key="active_model_selector",
        )
    with c_web:
        web_toggle = st.toggle("🌐 Web", value=True, key="toggle_web")
    with c_mail:
        gmail_toggle = st.toggle("✉️ Gmail", value=False, key="toggle_gmail")
    with c_docs:
        docs_toggle = st.toggle("📄 Docs", value=False, key="toggle_docs")
    with c_upload:
        uploaded_doc = st.file_uploader(
            "Upload Doc",
            type=["txt", "pdf"],
            label_visibility="collapsed",
            key="doc_uploader",
        )
    st.markdown('</div>', unsafe_allow_html=True)

# Document caching and status
current_chunks = None
current_doc_name = "Uploaded Document"
if uploaded_doc is not None:
    try:
        cache_key = f"{uploaded_doc.name}_{uploaded_doc.size}"
        if st.session_state.get("cached_doc_key") != cache_key:
            doc_data = extract_text_from_file(uploaded_doc.getvalue(), uploaded_doc.name)
            st.session_state["cached_doc_key"] = cache_key
            st.session_state["cached_doc_data"] = doc_data
        else:
            doc_data = st.session_state.get("cached_doc_data", {})

        current_chunks = doc_data.get("chunks", [])
        current_doc_name = uploaded_doc.name
        if doc_data.get("error"):
            st.caption(f"⚠️ {doc_data['error']}")
        elif current_chunks:
            st.caption(f"📄 Loaded **{uploaded_doc.name}** ({len(current_chunks)} chunks ready for RAG)")
    except Exception as doc_err:
        log_event(f"Error handling document upload: {repr(doc_err)}", level="error")
        st.caption(f"⚠️ Unable to read uploaded document: {str(doc_err)}")

# Prompt input
prompt = st.chat_input("Ask a question or enter an instruction...")
if prompt:
    # 1. Record & render user message
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    
    log_event(f"User sent prompt: {prompt[:60]}...")
    
    # 2. Assistant response via unified ask() streaming
    try:
        with st.chat_message("assistant"):
            stream = ask(
                provider=selected_model,
                messages=st.session_state.messages,
                web_enabled=web_toggle,
                docs_enabled=docs_toggle,
                doc_chunks=current_chunks,
                doc_filename=current_doc_name,
                email_enabled=gmail_toggle,
            )
            full_response = st.write_stream(stream)
        
        if full_response:
            st.session_state.messages.append({"role": "assistant", "content": full_response})
            # Dispatch background Sheets logging (non-blocking)
            sources_note = ""
            if "**Sources used:**" in full_response:
                sources_note = full_response.split("**Sources used:**")[-1].strip()
            log_conversation_async(selected_model, prompt, full_response, sources_note)
    except Exception as chat_err:
        log_event(f"Chat streaming error: {repr(chat_err)}", level="error")
        st.error(f"⚠️ An error occurred while generating the answer: {str(chat_err)}")
