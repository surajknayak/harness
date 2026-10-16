import json
import os
import traceback
from typing import Generator
from config import get_config
from logger import log_event
from web import search_web, format_search_results
from rag import retrieve_relevant_chunks, format_rag_context

WEB_TOOL_ANTHROPIC = [
    {
        "name": "web_search",
        "description": "Search the live web for current facts, news, documentation, or real-time information.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query keywords"}
            },
            "required": ["query"],
        },
    }
]

WEB_TOOL_OPENAI = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the live web for current facts, news, documentation, or real-time information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query keywords"}
                },
                "required": ["query"],
            },
        },
    }
]

def _extract_last_user_query(messages: list) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            return m.get("content", "")
    return ""

def _format_messages_for_anthropic(messages: list, additional_context: str = "") -> tuple[str, list]:
    system_prompt = (
        "You are a helpful, precise AI assistant in The Harness — a multi-model orchestrator. "
        "Ground your answers clearly and directly."
    )
    if additional_context:
        system_prompt += f"\n\n{additional_context}"

    formatted = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "")
        if role == "system":
            system_prompt += f"\n{content}"
        elif role in ["user", "assistant"]:
            if formatted and formatted[-1]["role"] == role:
                formatted[-1]["content"] += f"\n\n{content}"
            else:
                formatted.append({"role": role, "content": content})
                
    if formatted and formatted[0]["role"] != "user":
        formatted.insert(0, {"role": "user", "content": "Hello"})
        
    return system_prompt, formatted

def _format_messages_for_openai(messages: list, additional_context: str = "") -> list:
    system_content = (
        "You are a helpful, precise AI assistant in The Harness — a multi-model orchestrator. "
        "Ground your answers clearly and directly."
    )
    if additional_context:
        system_content += f"\n\n{additional_context}"

    formatted = [{"role": "system", "content": system_content}]
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "")
        if role in ["system", "user", "assistant"] and content:
            formatted.append({"role": role, "content": content})
    return formatted

def _render_sources_footer(sources: list) -> str:
    if not sources:
        return ""
    return f"\n\n---\n**Sources used:** {' · '.join(sources)}"

def ask(
    provider: str,
    messages: list,
    web_enabled: bool = False,
    docs_enabled: bool = False,
    doc_chunks: list | None = None,
    doc_filename: str = "Uploaded Document",
    email_enabled: bool = False,
) -> Generator[str, None, None]:
    """
    Unified generator interface for model querying across Claude, OpenAI, and Grok.
    Zero raw stack traces: catches all exceptions and logs full tracebacks silently.
    Produces detailed 'Sources used:' footer for capabilities that fired.
    """
    try:
        provider_lower = provider.lower()
        user_query = _extract_last_user_query(messages)
        sources_fired = []

        # -------------------------------------------------------------
        # 1. Document RAG Context Extraction
        # -------------------------------------------------------------
        doc_context = ""
        used_docs = False
        if docs_enabled:
            if doc_chunks:
                yield "📄 *Reading your document…*\n\n"
                relevant = retrieve_relevant_chunks(user_query, doc_chunks, top_k=4)
                if relevant:
                    doc_context = format_rag_context(relevant, filename=doc_filename)
                    used_docs = True
                    sources_fired.append(f"Docs — {len(relevant)} excerpt{'s' if len(relevant) != 1 else ''} ({doc_filename})")
            else:
                yield "⚠️ *Docs toggle is active, but no document is currently uploaded.*\n\n"

        # -------------------------------------------------------------
        # 2. Gmail IMAP Context Extraction
        # -------------------------------------------------------------
        email_context = ""
        used_email = False
        if email_enabled:
            yield "✉️ *Checking email…*\n\n"
            try:
                import importlib
                import gmail
                importlib.reload(gmail)
                mail_res = gmail.get_recent_emails()
                if mail_res.get("error"):
                    yield f"{mail_res['error']}\n\n"
                elif mail_res.get("messages"):
                    email_context = gmail.format_emails_for_prompt(mail_res["messages"])
                    used_email = True
                    m_count = len(mail_res["messages"])
                    sources_fired.append(f"Email — {m_count} recent message{'s' if m_count != 1 else ''}")
                else:
                    sources_fired.append("Email — no recent messages")
                    yield "✉️ *No recent emails found in mailbox.*\n\n"
            except Exception as mail_exc:
                log_event(f"Unexpected email handling failure: {traceback.format_exc()}", level="error")
                yield f"⚠️ Gmail Diagnostic: {str(mail_exc)}\n\n"

        # Combined grounded context
        grounded_context = ""
        if doc_context:
            grounded_context += f"{doc_context}\n\n"
        if email_context:
            grounded_context += f"{email_context}\n\n"

        # -------------------------------------------------------------
        # 3. Model Dispatch: Claude
        # -------------------------------------------------------------
        if "claude" in provider_lower or "anthropic" in provider_lower:
            api_key = get_config("ANTHROPIC_API_KEY")
            if not api_key:
                log_event("Claude call aborted: ANTHROPIC_API_KEY is missing.", level="warning")
                yield "⚠️ **Anthropic API key is missing.** Please configure `ANTHROPIC_API_KEY` in Settings (⚙️) or in your `.env` file."
                return

            system_prompt, anthropic_msgs = _format_messages_for_anthropic(messages, grounded_context)
            if not anthropic_msgs:
                yield "No message provided."
                return

            log_event(f"Starting Claude API call (model: claude-sonnet-4-6, web: {web_enabled}, docs: {used_docs}, email: {used_email})")
            
            try:
                import anthropic
                client = anthropic.Anthropic(api_key=api_key)
                target_model = "claude-sonnet-4-6"
                tools = WEB_TOOL_ANTHROPIC if web_enabled else None
                
                def _create_message(model_name, current_messages, tools_arg=None):
                    kwargs = {
                        "model": model_name,
                        "max_tokens": 4096,
                        "system": system_prompt,
                        "messages": current_messages,
                    }
                    if tools_arg:
                        kwargs["tools"] = tools_arg
                    return client.messages.create(**kwargs)

                # Pure streaming when web tools are disabled
                if not tools:
                    try:
                        with client.messages.stream(
                            model=target_model,
                            max_tokens=4096,
                            system=system_prompt,
                            messages=anthropic_msgs,
                        ) as stream:
                            for text in stream.text_stream:
                                yield text
                    except (anthropic.NotFoundError, anthropic.BadRequestError) as model_err:
                        target_model = "claude-3-5-sonnet-20241022"
                        log_event(f"Model claude-sonnet-4-6 fallback to {target_model}: {model_err}", level="warning")
                        with client.messages.stream(
                            model=target_model,
                            max_tokens=4096,
                            system=system_prompt,
                            messages=anthropic_msgs,
                        ) as stream:
                            for text in stream.text_stream:
                                yield text

                    if sources_fired:
                        yield _render_sources_footer(sources_fired)
                    log_event("Claude API call completed successfully.")
                    return

                try:
                    response = _create_message(target_model, anthropic_msgs, tools)
                except (anthropic.NotFoundError, anthropic.BadRequestError) as model_err:
                    target_model = "claude-3-5-sonnet-20241022"
                    log_event(f"Model claude-sonnet-4-6 not found, falling back to {target_model}", level="warning")
                    response = _create_message(target_model, anthropic_msgs, tools)

                used_web = False
                if response.stop_reason == "tool_use":
                    tool_use_block = next((b for b in response.content if getattr(b, "type", "") == "tool_use"), None)
                    if tool_use_block and tool_use_block.name == "web_search":
                        used_web = True
                        search_query = tool_use_block.input.get("query", user_query)
                        yield "🌐 *Searching the web…*\n\n"
                        search_res = search_web(search_query, max_results=5)
                        search_count = len(search_res.get("results", []))
                        sources_fired.append(f"Web — {search_count} result{'s' if search_count != 1 else ''}")
                        search_context = format_search_results(search_res)

                        conv = list(anthropic_msgs)
                        conv.append({"role": "assistant", "content": response.content})
                        conv.append({
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": tool_use_block.id,
                                    "content": search_context,
                                }
                            ],
                        })

                        with client.messages.stream(
                            model=target_model,
                            max_tokens=4096,
                            system=system_prompt,
                            messages=conv,
                        ) as stream:
                            for text in stream.text_stream:
                                yield text
                else:
                    for block in response.content:
                        if getattr(block, "type", "") == "text":
                            yield block.text

                if sources_fired:
                    yield _render_sources_footer(sources_fired)

                log_event("Claude API call completed successfully.")
            except Exception as exc:
                log_event(f"Claude API call failed: {traceback.format_exc()}", level="error")
                yield f"⚠️ **Anthropic API Error:** {str(exc)}"

        # -------------------------------------------------------------
        # 4. Model Dispatch: OpenAI (gpt-4o)
        # -------------------------------------------------------------
        elif "openai" in provider_lower or "gpt" in provider_lower:
            api_key = get_config("OPENAI_API_KEY")
            if not api_key:
                log_event("OpenAI call aborted: OPENAI_API_KEY is missing.", level="warning")
                yield "⚠️ **OpenAI API key is missing.** Please configure `OPENAI_API_KEY` in Settings (⚙️) or in your `.env` file."
                return

            openai_msgs = _format_messages_for_openai(messages, grounded_context)
            if len(openai_msgs) <= 1:
                yield "No message provided."
                return

            log_event(f"Starting OpenAI API call (model: gpt-4o, web: {web_enabled}, docs: {used_docs}, email: {used_email})")
            try:
                import openai
                client = openai.OpenAI(api_key=api_key)
                tools = WEB_TOOL_OPENAI if web_enabled else None
                
                if tools:
                    response = client.chat.completions.create(
                        model="gpt-4o",
                        messages=openai_msgs,
                        tools=tools,
                    )
                    choice = response.choices[0]
                    if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
                        tool_call = choice.message.tool_calls[0]
                        if tool_call.function.name == "web_search":
                            try:
                                args = json.loads(tool_call.function.arguments)
                                search_query = args.get("query", user_query)
                            except Exception:
                                search_query = user_query

                            yield "🌐 *Searching the web…*\n\n"
                            search_res = search_web(search_query, max_results=5)
                            search_count = len(search_res.get("results", []))
                            sources_fired.append(f"Web — {search_count} result{'s' if search_count != 1 else ''}")
                            search_context = format_search_results(search_res)

                            conv = list(openai_msgs)
                            conv.append(choice.message)
                            conv.append({
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "content": search_context,
                            })

                            stream = client.chat.completions.create(
                                model="gpt-4o",
                                messages=conv,
                                stream=True,
                            )
                            for chunk in stream:
                                if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                                    yield chunk.choices[0].delta.content
                                    
                            if sources_fired:
                                yield _render_sources_footer(sources_fired)
                            log_event("OpenAI API call with web search completed successfully.")
                            return

                    if choice.message.content:
                        yield choice.message.content
                        if sources_fired:
                            yield _render_sources_footer(sources_fired)
                        log_event("OpenAI API direct call completed.")
                        return

                stream = client.chat.completions.create(
                    model="gpt-4o",
                    messages=openai_msgs,
                    stream=True,
                )
                for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content
                        
                if sources_fired:
                    yield _render_sources_footer(sources_fired)
                log_event("OpenAI API call completed successfully.")
            except Exception as exc:
                log_event(f"OpenAI API call failed: {traceback.format_exc()}", level="error")
                yield f"⚠️ **OpenAI API Error:** {str(exc)}"

        # -------------------------------------------------------------
        # 5. Model Dispatch: Grok (grok-2-latest)
        # -------------------------------------------------------------
        elif "grok" in provider_lower or "xai" in provider_lower:
            api_key = get_config("XAI_API_KEY")
            if not api_key:
                log_event("Grok call aborted: XAI_API_KEY is missing.", level="warning")
                yield "⚠️ **xAI (Grok) API key is missing.** Please configure `XAI_API_KEY` in Settings (⚙️) or in your `.env` file."
                return

            grok_msgs = _format_messages_for_openai(messages, grounded_context)
            if len(grok_msgs) <= 1:
                yield "No message provided."
                return

            log_event(f"Starting Grok API call (model: grok-2-latest, web: {web_enabled}, docs: {used_docs}, email: {used_email})")
            try:
                import openai
                client = openai.OpenAI(
                    api_key=api_key,
                    base_url="https://api.x.ai/v1",
                )
                tools = WEB_TOOL_OPENAI if web_enabled else None
                
                if tools:
                    try:
                        response = client.chat.completions.create(
                            model="grok-2-latest",
                            messages=grok_msgs,
                            tools=tools,
                        )
                        choice = response.choices[0]
                        if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
                            tool_call = choice.message.tool_calls[0]
                            if tool_call.function.name == "web_search":
                                try:
                                    args = json.loads(tool_call.function.arguments)
                                    search_query = args.get("query", user_query)
                                except Exception:
                                    search_query = user_query

                                yield "🌐 *Searching the web…*\n\n"
                                search_res = search_web(search_query, max_results=5)
                                search_count = len(search_res.get("results", []))
                                sources_fired.append(f"Web — {search_count} result{'s' if search_count != 1 else ''}")
                                search_context = format_search_results(search_res)

                                conv = list(grok_msgs)
                                conv.append(choice.message)
                                conv.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "content": search_context,
                                })

                                stream = client.chat.completions.create(
                                    model="grok-2-latest",
                                    messages=conv,
                                    stream=True,
                                )
                                for chunk in stream:
                                    if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                                        yield chunk.choices[0].delta.content
                                        
                                if sources_fired:
                                    yield _render_sources_footer(sources_fired)
                                log_event("Grok API call with web tool completed successfully.")
                                return

                        if choice.message.content:
                            yield choice.message.content
                            if sources_fired:
                                yield _render_sources_footer(sources_fired)
                            log_event("Grok API call without web tool completed.")
                            return

                    except Exception as tool_err:
                        log_event(f"Grok tool-calling failed, falling back to direct Tavily injection: {traceback.format_exc()}", level="warning")
                        yield "🌐 *Searching the web…*\n\n"
                        search_res = search_web(user_query, max_results=5)
                        search_count = len(search_res.get("results", []))
                        sources_fired.append(f"Web — {search_count} result{'s' if search_count != 1 else ''}")
                        search_context = format_search_results(search_res)
                        
                        fallback_msgs = list(grok_msgs)
                        fallback_msgs.insert(1, {
                            "role": "system",
                            "content": f"Grounded Context from Web Search:\n{search_context}",
                        })
                        
                        stream = client.chat.completions.create(
                            model="grok-2-latest",
                            messages=fallback_msgs,
                            stream=True,
                        )
                        for chunk in stream:
                            if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                                yield chunk.choices[0].delta.content
                                
                        if sources_fired:
                            yield _render_sources_footer(sources_fired)
                        return

                stream = client.chat.completions.create(
                    model="grok-2-latest",
                    messages=grok_msgs,
                    stream=True,
                )
                for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content
                        
                if sources_fired:
                    yield _render_sources_footer(sources_fired)
                log_event("Grok API call completed successfully.")
            except Exception as exc:
                log_event(f"Grok API call failed: {traceback.format_exc()}", level="error")
                yield f"⚠️ **Grok API Error:** {str(exc)}"

        else:
            err = f"Unsupported provider: '{provider}'"
            log_event(err, level="warning")
            yield f"⚠️ {err}"

    except Exception as top_level_exc:
        log_event(f"Fatal error in ask(): {traceback.format_exc()}", level="error")
        yield f"⚠️ **Error generating response:** {str(top_level_exc)}"
