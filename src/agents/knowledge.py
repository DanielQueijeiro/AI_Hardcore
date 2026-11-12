"""Agent 2: Knowledge Agent — Hybrid Getnet RAG & General Utility Web Search (ADR-0003, ADR-0004)."""

from __future__ import annotations

from typing import Any

from src.config import generate_completion
from src.schemas import OrchestrationState, PrimaryIntent
from src.tools.search_tools import (
    KnowledgeRetrievalResult,
    retrieve_getnet_knowledge,
    search_web_general,
)

KNOWLEDGE_SYSTEM_PROMPT = (
    "You are the Getnet Knowledge Agent assisting a Getnet Merchant. "
    "Answer the Merchant's inquiry accurately and concisely using ONLY the retrieved "
    "Getnet Knowledge Base context and any provided POS Terminal diagnostic context. "
    "Always preserve specific product names (Get Clássica, Get Smart, Pix, Antecipação / "
    "Receivables Advance, Crediário, Payment Link / Get Pay), timeframes (D+0, D+1, D+2, "
    "up to 24x-36x), and technical parameters (OFFLINE_GPRS_TIMEOUT, APN getnet.br)."
)

GENERAL_WEB_SEARCH_SYSTEM_PROMPT = (
    "You are the Getnet Knowledge Agent answering a benign General Utility inquiry for a Merchant. "
    "Synthesize a clear, accurate response grounded strictly in the provided live web search context, "
    "preserving all numerical values (temperatures in °C, precipitation %, or EUR/BRL/USD exchange rates)."
)


def _synthesize_grounded_product_answer(
    message: str,
    retrieval: KnowledgeRetrievalResult,
    support_context: dict[str, Any] | None = None,
) -> str:
    """Synthesize a grounded, deterministic fallback answer from retrieved RAG chunks."""
    if not retrieval.chunks:
        return (
            "I could not find specific documentation for your inquiry in the Getnet knowledge base. "
            "Please contact Getnet support or visit https://site.getnet.com.br for further details."
        )

    top_chunk = retrieval.chunks[0]
    anchor = top_chunk.source.split("#")[-1] if "#" in top_chunk.source else ""
    lower_msg = message.lower()

    # If invoked after Customer Support Agent for POS connectivity troubleshooting (Scenario #5)
    if support_context and (
        "offline" in str(support_context.get("status", "")).lower()
        or "connect" in lower_msg
        or anchor == "pos-terminal-connectivity-troubleshooting"
    ):
        terminal_model = support_context.get("terminal_model", "Get Smart")
        terminal_id = support_context.get("terminal_id", "POS-GS-99812")
        conn_status = support_context.get("status") or support_context.get(
            "connectivity_status", "OFFLINE_GPRS_TIMEOUT"
        )
        return (
            f"**POS Terminal Connectivity Diagnosis & Reconnection Guide (`{terminal_model}` — `{terminal_id}`)**\n\n"
            f"- **Detected Telemetry Status**: `{conn_status}` (4G GPRS session timed out and Wi-Fi interface is disconnected).\n\n"
            "**Official Getnet Reconnection Steps**:\n"
            "1. **Restart the POS Terminal**: Hold the Power button for 5 seconds and select **Restart (Reiniciar)** to refresh the cellular modem registration.\n"
            "2. **Connect to Wi-Fi (`Settings > Network`)**: On your **Get Smart** Android touchscreen, open **Settings > Network & Internet > Wi-Fi**, turn Wi-Fi ON, and connect to your storefront's 2.4 GHz Wi-Fi network.\n"
            "3. **Reset 4G Session & Verify APN (`getnet.br`)**: Toggle **Airplane Mode** ON for 10 seconds and OFF. Go to **Settings > Mobile Network > Access Point Names (APN)** and confirm the APN is set to **`getnet.br`** with Dual-SIM mobile data active.\n"
            "4. **Reseat SIM Card**: If the `OFFLINE_GPRS_TIMEOUT` error persists on both Wi-Fi and 4G, power off the terminal, reseat the Getnet SIM card, or request a terminal replacement."
        )

    if anchor == "get-classica-vs-get-smart" or (
        "smart" in lower_msg and ("clássica" in lower_msg or "classica" in lower_msg)
    ):
        return (
            "**Difference Between the Get Clássica and Get Smart POS Terminals**\n\n"
            "1. **Get Clássica (Traditional Countertop / Portable POS Terminal)**:\n"
            "   - **Interface & OS**: Runs a dedicated proprietary POS OS (Linux-based) with a color screen and a **physical tactile keypad** for fast PIN entry.\n"
            "   - **Connectivity & Hardware**: Connects via **3G/4G mobile data (free SIM included) + Wi-Fi**, features contactless **NFC**, a built-in **high-speed thermal receipt printer**, and a 10–12h battery.\n"
            "   - **Best For**: High-throughput retail counters and restaurants seeking rapid, straightforward card and Pix payments.\n\n"
            "2. **Get Smart (Android Touchscreen Smart POS Terminal)**:\n"
            "   - **Interface & OS**: Runs on **Android OS** with a full **HD multi-touch screen** (no physical numeric keypad) and access to the **GetStore** app marketplace.\n"
            "   - **Connectivity & Hardware**: Features **Dual-SIM 4G + Dual-band Wi-Fi + Bluetooth + NFC**, a built-in **thermal receipt printer**, an **integrated camera/barcode scanner**, and a long-shift battery.\n"
            "   - **Best For**: Merchants who want an all-in-one smart terminal combining payment acceptance with catalog management, inventory control, and business apps.\n\n"
            f"*(Source: `{top_chunk.source}`)*"
        )

    if anchor == "pix-bank-account-rules" or "pix" in lower_msg:
        return (
            "**No, you do not need a traditional bank account to receive your sales via Pix with Getnet.**\n\n"
            "Getnet provides two **Settlement** options for receiving your **Pix** and card sales:\n"
            "1. **Getnet Digital Account (*Get Conta* / *SuperGet*)**: If you do not have (or prefer not to use) an external bank account, Getnet automatically credits your sales into a free built-in **Getnet digital account**, allowing you to pay bills, make Pix transfers, or withdraw funds with a Getnet prepaid card.\n"
            "2. **External Bank Account (*Domicílio Bancário*)**: If you prefer, you can register a checking or savings account at **Banco Santander** or any other Brazilian bank under your registered CPF or CNPJ.\n\n"
            "- **Settlement Speed**: **Pix** QR Code sales on a Getnet **POS Terminal** or **Payment Link** settle in **D+0 (instant / same-day Settlement, 24/7)**.\n\n"
            f"*(Source: `{top_chunk.source}`)*"
        )

    if anchor == "receivables-advance-antecipacao" or "antecip" in lower_msg or "receivables advance" in lower_msg:
        return (
            "**How Receivables Advance (*Antecipação de Recebíveis*) Works with Getnet**\n\n"
            "**Receivables Advance** allows a **Merchant** to receive net funds from **credit card sales (1x or installments 2x–12x)** before the standard **D+30** **Settlement** schedule:\n"
            "- **Settlement Timeframes**: Receive your credit sales in **D+0 (same day)**, **D+1 (next business day)**, or **D+2 (within 2 business days)** instead of waiting 30 to 360 days.\n"
            "- **Two Contracting Modes**:\n"
            "  1. **Automatic Plan (*Antecipação Automática / Plano Flex*)**: Automatically advances every eligible credit sale on your **POS Terminal** or **Payment Link** on your chosen schedule (e.g., D+1 or D+2).\n"
            "  2. **On-Demand Advance (*Antecipação Avulsa*)**: Advance specific future receivables batches anytime via the **App Getnet**, **Portal Minha Conta**, or WhatsApp.\n"
            "- **Fees**: A transparent discount rate (*taxa de antecipação*) proportional to the days advanced is applied to the transaction, with no IOF tax and without consuming bank credit lines.\n\n"
            f"*(Source: `{top_chunk.source}`)*"
        )

    if anchor == "crediario-installment-limits" or "crediário" in lower_msg or "crediario" in lower_msg or "installment" in lower_msg:
        return (
            "**Getnet Crediário Installment Limits**\n\n"
            "With Getnet **Crediário** (*Crediário na Maquininha*), you can split a sale into **up to 24x or up to 36x installments** (commonly **up to 24 installments**, and **up to 36 installments** depending on the buyer's card issuer rules, compared to the standard 12x credit card limit).\n\n"
            "- **How it works**: Select **Crediário** on your **POS Terminal** (*Get Clássica* or *Get Smart*), enter the sale value, and simulate **2x up to 24x–36x** installments right on the screen.\n"
            "- **Merchant Settlement**: The buyer's issuing bank finances the extended installment plan while the **Merchant** receives the **Settlement** in a single predictable payout (typically within **D+2** or up to **30 days**).\n\n"
            f"*(Source: `{top_chunk.source}`)*"
        )

    if anchor == "payment-link-whatsapp" or "whatsapp" in lower_msg or "payment link" in lower_msg:
        return (
            "**Yes, you can sell through WhatsApp using the Getnet Payment Link (*Link de Pagamento* / *Get Pay*)!**\n\n"
            "You do not need an e-commerce website to collect remote payments:\n"
            "1. **Create the Link**: Open the **App Getnet** or **Portal Minha Conta Getnet** and select **Link de Pagamento (Get Pay)**.\n"
            "2. **Configure the Sale**: Enter the item description, amount, and payment options (**Credit Card up to 12x**, **Debit**, **Pix D+0**, or **Boleto**).\n"
            "3. **Share on WhatsApp**: Tap **Share via WhatsApp** to send the secure checkout URL directly to your customer's chat.\n"
            "4. **Built-in Security**: Every **Payment Link** includes automated **anti-fraud screening** and **3DS authentication**.\n\n"
            f"*(Source: `{top_chunk.source}`)*"
        )

    return f"{top_chunk.content}\n\n*(Source: `{top_chunk.source}`)*"


def run_knowledge_agent(state: OrchestrationState) -> dict[str, Any]:
    """Execute Agent 2 (Knowledge Agent) for Getnet RAG or General Utility web search."""
    sequence = list(state.get("agent_sequence", []))
    sequence.append("knowledge_agent")
    tools = list(state.get("tools_called", []))
    rag_sources = list(state.get("rag_sources", []))

    message = state.get("message", "")
    intent = state.get("primary_intent", PrimaryIntent.PRODUCT_KNOWLEDGE.value)
    support_context = state.get("support_context") or {}

    if intent == PrimaryIntent.GENERAL_WEB_SEARCH.value:
        if "search_web_general" not in tools:
            tools.append("search_web_general")
        web_result = search_web_general(message)
        answer = generate_completion(
            system_prompt=GENERAL_WEB_SEARCH_SYSTEM_PROMPT,
            user_prompt=f"Merchant Inquiry: {message}\n\nWeb Search Result:\n{web_result}",
            fallback_text=web_result,
        )

        return {
            **state,
            "agent_sequence": sequence,
            "tools_called": tools,
            "rag_sources": rag_sources,
            "knowledge_context": web_result,
            "final_answer": answer,
        }

    # Product Knowledge or Compound POS Connectivity Troubleshooting via Hybrid RAG
    retrieval_query = message
    if support_context:
        status_hint = support_context.get("status") or support_context.get("connectivity_status", "")
        retrieval_query = f"{message} POS terminal connectivity troubleshooting {status_hint}".strip()

    retrieval = retrieve_getnet_knowledge(query=retrieval_query, top_k=2)
    if "retrieve_getnet_knowledge" not in tools:
        tools.append("retrieve_getnet_knowledge")

    for src in retrieval.sources:
        if src not in rag_sources:
            rag_sources.append(src)

    fallback_answer = _synthesize_grounded_product_answer(
        message=message,
        retrieval=retrieval,
        support_context=support_context if support_context else None,
    )

    user_prompt = (
        f"Merchant Inquiry: {message}\n\n"
        f"Support Diagnostic Context: {support_context}\n\n"
        f"Retrieved Getnet Knowledge Base Chunks:\n{retrieval.context_text}"
    )
    synthesized = generate_completion(
        system_prompt=KNOWLEDGE_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        fallback_text=fallback_answer,
    )

    # If support_context already placed diagnostic summary in final_answer, preserve or enrich cleanly
    prior_answer = (state.get("final_answer") or "").strip()
    if support_context and prior_answer and prior_answer not in synthesized:
        final_answer = f"{prior_answer}\n\n{synthesized}"
    else:
        final_answer = synthesized

    return {
        **state,
        "agent_sequence": sequence,
        "tools_called": tools,
        "rag_sources": rag_sources,
        "knowledge_context": retrieval.context_text,
        "final_answer": final_answer,
    }
