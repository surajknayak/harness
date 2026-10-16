# The Harness ⚡

A clean, multi-model AI chat orchestrator capable of drawing simultaneously on **Web Search**, **Document RAG (.txt / .pdf)**, and **Gmail (read-only IMAP)**, with optional background **Google Sheets logging**.

Built with Streamlit, following a minimalist, high-end light theme.

---

## 🌟 Capabilities & Providers

- **Models**:
  - Claude (`claude-sonnet-4-6` via Anthropic SDK, with version fallback)
  - OpenAI (`gpt-4o` via OpenAI SDK)
  - Grok (`grok-2-latest` via xAI endpoint `https://api.x.ai/v1`)
- **🌐 Web Search**: Tavily search API, capped at 5 snippets, dynamic delight indicator (`🌐 Searching the web…`).
- **📄 Document RAG**: In-memory text extraction for `.txt` and `.pdf` (via `pypdf`), 800-char chunks / 100-char overlap, keyword relevance scoring (no external vector DB required), and delight indicator (`📄 Reading your document…`).
- **✉️ Gmail IMAP (Read-Only)**: Read-only sequence fetching with `BODY.PEEK[]` (messages never marked read), 10MB buffer limit, automatic whitespace/`\xa0` password sanitization, and delight indicator (`✉️ Checking email…`).
- **📊 Google Sheets Logger**: Optional non-blocking background daemon thread appending conversation rows to a target Google Sheet.
- **Sources Attribution**: Detailed footer under answers showing exactly which capabilities fired with counts (e.g. `Web — 3 results · Docs — 2 excerpts (sample.txt) · Email — no recent messages`).
- **Resilience**: Runs with any subset of keys present; zero raw stack traces in the UI.

---

## ⚙️ Environment Variables

The app runs with any subset of keys present. Set these in your environment or via the in-app **⚙️ Settings** modal:

| Variable | Description | Required |
|---|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API key for Claude | For Claude |
| `OPENAI_API_KEY` | OpenAI API key for `gpt-4o` | For OpenAI |
| `XAI_API_KEY` | xAI API key for `grok-2-latest` | For Grok |
| `TAVILY_API_KEY` | Tavily Search API key | For Web Search |
| `GMAIL_USER` | Gmail address | For Gmail IMAP |
| `GMAIL_APP_PASSWORD` | 16-character Google App Password | For Gmail IMAP |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Service account JSON string or path | Optional (Logging) |
| `TARGET_SHEET_ID` | Google Sheet ID for appending logs | Optional (Logging) |

---

## 🚀 Render Deployment Setup

### 1. Build & Start Commands
- **Environment**: `Python 3`
- **Build Command**:
  ```bash
  pip install -r requirements.txt
  ```
- **Start Command**:
  ```bash
  streamlit run app.py --server.port $PORT --server.address 0.0.0.0
  ```

### 2. Setting Environment Variables
Add your API keys under **Environment Variables** in your Render service dashboard.

---

## 💻 Local Development

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Copy environment template:
   ```bash
   cp .env.example .env
   ```
3. Run the application:
   ```bash
   streamlit run app.py
   ```
4. Access the web interface at `http://localhost:8501`.
