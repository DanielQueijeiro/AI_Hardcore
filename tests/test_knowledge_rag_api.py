"""Integration tests for Knowledge Agent Hybrid Getnet RAG via POST /chat (Ticket 02)."""

import httpx
import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.rag.ingest import load_hybrid_corpus, scrape_getnet_website
from src.rag.retriever import GetnetHybridRetriever


def test_scenario_1_pos_terminal_comparison_get_classica_vs_get_smart() -> None:
    """Scenario #1: Product comparison inquiry retrieves Getnet KB and explains Get Clássica vs Get Smart."""
    client = TestClient(app)
    response = client.post(
        "/chat",
        json={
            "message": "What's the difference between the Get Clássica and the Get Smart?",
            "user_id": "cliente1988",
        },
    )

    assert response.status_code == 200
    data = response.json()
    orch = data["orchestration"]

    assert orch["safety_tier"] == "GETNET_DOMAIN"
    assert orch["primary_intent"] == "PRODUCT_KNOWLEDGE"
    assert orch["agent_sequence"] == ["router_agent", "knowledge_agent"]
    assert orch["tools_called"] == ["retrieve_getnet_knowledge"]
    assert "data/getnet_knowledge_base.md#get-classica-vs-get-smart" in orch["rag_sources"]

    answer_lower = data["answer"].lower()
    assert "get clássica" in answer_lower or "get classica" in answer_lower
    assert "get smart" in answer_lower
    assert "android" in answer_lower and "touchscreen" in answer_lower
    assert "physical" in answer_lower and "keypad" in answer_lower


def test_scenario_4_pix_bank_account_requirements_and_digital_account_options() -> None:
    """Scenario #4: Pix bank account inquiry clarifies Getnet digital account vs traditional bank account."""
    client = TestClient(app)
    response = client.post(
        "/chat",
        json={
            "message": "Do I need a bank account to receive my sales via Pix?",
            "user_id": "cliente1988",
        },
    )

    assert response.status_code == 200
    data = response.json()
    orch = data["orchestration"]

    assert orch["safety_tier"] == "GETNET_DOMAIN"
    assert orch["primary_intent"] == "PRODUCT_KNOWLEDGE"
    assert orch["agent_sequence"] == ["router_agent", "knowledge_agent"]
    assert orch["tools_called"] == ["retrieve_getnet_knowledge"]
    assert "data/getnet_knowledge_base.md#pix-bank-account-rules" in orch["rag_sources"]

    answer_lower = data["answer"].lower()
    assert "no" in answer_lower
    assert "digital account" in answer_lower
    assert "bank account" in answer_lower
    assert "d+0" in answer_lower or "instant" in answer_lower


def test_scenario_6_receivables_advance_antecipacao_mechanics_and_timeframes() -> None:
    """Scenario #6: Receivables Advance inquiry explains antecipação timeframes and contracting modes."""
    client = TestClient(app)
    response = client.post(
        "/chat",
        json={
            "message": "How does receivables advance (antecipação) work with Getnet?",
            "user_id": "cliente1988",
        },
    )

    assert response.status_code == 200
    data = response.json()
    orch = data["orchestration"]

    assert orch["safety_tier"] == "GETNET_DOMAIN"
    assert orch["primary_intent"] == "PRODUCT_KNOWLEDGE"
    assert orch["agent_sequence"] == ["router_agent", "knowledge_agent"]
    assert orch["tools_called"] == ["retrieve_getnet_knowledge"]
    assert "data/getnet_knowledge_base.md#receivables-advance-antecipacao" in orch["rag_sources"]

    answer_lower = data["answer"].lower()
    assert "receivables advance" in answer_lower or "antecipação" in answer_lower
    assert "d+0" in answer_lower or "d+1" in answer_lower or "d+2" in answer_lower
    assert "d+30" in answer_lower
    assert "automatic" in answer_lower or "on-demand" in answer_lower


def test_scenario_9_crediario_installment_limits_up_to_24x_36x() -> None:
    """Scenario #9: Crediário inquiry states extended installment limits (up to 24x-36x)."""
    client = TestClient(app)
    response = client.post(
        "/chat",
        json={
            "message": "How many installments can I split a sale into with the crediário?",
            "user_id": "cliente1988",
        },
    )

    assert response.status_code == 200
    data = response.json()
    orch = data["orchestration"]

    assert orch["safety_tier"] == "GETNET_DOMAIN"
    assert orch["primary_intent"] == "PRODUCT_KNOWLEDGE"
    assert orch["agent_sequence"] == ["router_agent", "knowledge_agent"]
    assert orch["tools_called"] == ["retrieve_getnet_knowledge"]
    assert "data/getnet_knowledge_base.md#crediario-installment-limits" in orch["rag_sources"]

    answer_lower = data["answer"].lower()
    assert "crediário" in answer_lower or "crediario" in answer_lower
    assert "24x" in answer_lower or "24 installments" in answer_lower
    assert "36x" in answer_lower or "36 installments" in answer_lower


def test_scenario_10_selling_via_whatsapp_using_payment_link() -> None:
    """Scenario #10: Payment Link inquiry confirms selling via WhatsApp with Get Pay."""
    client = TestClient(app)
    response = client.post(
        "/chat",
        json={
            "message": "Can I sell through WhatsApp using the Payment Link?",
            "user_id": "cliente1988",
        },
    )

    assert response.status_code == 200
    data = response.json()
    orch = data["orchestration"]

    assert orch["safety_tier"] == "GETNET_DOMAIN"
    assert orch["primary_intent"] == "PRODUCT_KNOWLEDGE"
    assert orch["agent_sequence"] == ["router_agent", "knowledge_agent"]
    assert orch["tools_called"] == ["retrieve_getnet_knowledge"]
    assert "data/getnet_knowledge_base.md#payment-link-whatsapp" in orch["rag_sources"]

    answer_lower = data["answer"].lower()
    assert "yes" in answer_lower
    assert "whatsapp" in answer_lower
    assert "payment link" in answer_lower or "get pay" in answer_lower
    assert "pix" in answer_lower and "credit" in answer_lower


def test_pos_connectivity_troubleshooting_rag_enrichment_for_scenario_5() -> None:
    """Scenario #5 enrichment: Knowledge Agent merges POS telemetry with APN getnet.br & Wi-Fi steps."""
    client = TestClient(app)
    response = client.post(
        "/chat",
        json={
            "message": "My card machine won't connect to the internet, what should I do?",
            "user_id": "cliente1988",
        },
    )

    assert response.status_code == 200
    data = response.json()
    orch = data["orchestration"]

    assert orch["agent_sequence"] == ["router_agent", "customer_support_agent", "knowledge_agent"]
    assert "retrieve_getnet_knowledge" in orch["tools_called"]
    assert "data/getnet_knowledge_base.md#pos-terminal-connectivity-troubleshooting" in orch["rag_sources"]

    answer_lower = data["answer"].lower()
    assert "offline_gprs_timeout" in answer_lower
    assert "getnet.br" in answer_lower
    assert "wi-fi" in answer_lower


def test_hybrid_rag_ingestion_succeeds_when_getnet_website_unreachable_or_mocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hybrid RAG ingestion degrades gracefully when getnet.net times out and parses HTML when online."""
    # 1. Simulate network timeout / WAF block on getnet.net
    def _raise_timeout(*args: object, **kwargs: object) -> None:
        raise httpx.ConnectTimeout("Simulated timeout to https://www.getnet.net/en")

    monkeypatch.setattr(httpx, "get", _raise_timeout)
    assert scrape_getnet_website("https://www.getnet.net/en") == []

    corpus_offline = load_hybrid_corpus(enable_live_scrape=True)
    assert len(corpus_offline) >= 6
    retriever = GetnetHybridRetriever(chunks=corpus_offline)
    top_hits = retriever.retrieve("What is the difference between Get Clássica and Get Smart?", top_k=1)
    assert len(top_hits) == 1
    assert top_hits[0].source == "data/getnet_knowledge_base.md#get-classica-vs-get-smart"

    # 2. Simulate valid HTML response from https://www.getnet.net/en
    class _FakeResponse:
        status_code = 200
        text = (
            "<html><body>"
            "<h1>Getnet Global Payment Solutions for Merchants</h1>"
            "<p>Getnet offers POS Terminals, Tap on Phone, Payment Link, and digital checkout across Latin America and Europe.</p>"
            "</body></html>"
        )

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse())
    scraped_chunks = scrape_getnet_website("https://www.getnet.net/en")
    assert len(scraped_chunks) == 1
    assert scraped_chunks[0].source == "https://www.getnet.net/en"
    assert "Getnet Global Payment Solutions" in scraped_chunks[0].content
