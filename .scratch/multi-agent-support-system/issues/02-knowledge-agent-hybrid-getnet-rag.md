# 02: Knowledge Agent — Hybrid Getnet RAG for Product & Service Inquiries

**What to build:** Deliver end-to-end resolution of Getnet product and service **Inquiries** through `POST /chat` (`router_agent` → `knowledge_agent`). Ingest and index Getnet knowledge from both live web scraping (`https://www.getnet.net/en` with graceful timeout/WAF resilience) and a curated Getnet Brazil product catalog covering **POS Terminal** models (*Get Clássica* vs. *Get Smart*), **Pix** account rules, **Receivables Advance** (*Antecipação*), **Crediário** installment limits, **Payment Link** (*Link de Pagamento* via WhatsApp), and **POS Terminal** network troubleshooting into a local CPU ONNX vector store. When a **Merchant** submits a product **Inquiry**, the **Knowledge Agent** retrieves relevant chunks via `retrieve_getnet_knowledge`, synthesizes an accurate grounded answer, and cites the retrieved sources in `orchestration.rag_sources`.

**Blocked by:** 01: Walking Skeleton — POST /chat API, State Graph & Router Safety Policy Guardrail

**Status:** resolved

- [x] Official Scenario **#1** (*"What's the difference between the Get Clássica and the Get Smart?"*) routes through `["router_agent", "knowledge_agent"]`, calls `["retrieve_getnet_knowledge"]`, populates `rag_sources`, and explains the differences between both **POS Terminal** models.
- [x] Official Scenario **#4** (*"Do I need a bank account to receive my sales via Pix?"*) routes through `["router_agent", "knowledge_agent"]`, calls `["retrieve_getnet_knowledge"]`, and clarifies Getnet digital account vs. traditional bank account **Settlement** options for **Pix**.
- [x] Official Scenario **#6** (*"How does receivables advance (antecipação) work with Getnet?"*) routes through `["router_agent", "knowledge_agent"]`, calls `["retrieve_getnet_knowledge"]`, and explains **Receivables Advance** mechanics and timeframes.
- [x] Official Scenario **#9** (*"How many installments can I split a sale into with the crediário?"*) routes through `["router_agent", "knowledge_agent"]`, calls `["retrieve_getnet_knowledge"]`, and states the **Crediário** installment limits.
- [x] Official Scenario **#10** (*"Can I sell through WhatsApp using the Payment Link?"*) routes through `["router_agent", "knowledge_agent"]`, calls `["retrieve_getnet_knowledge"]`, and confirms how **Merchants** share a **Payment Link** over WhatsApp.
- [x] RAG ingestion runs with local CPU embeddings at $0.00 cost and succeeds even when external scraping of `getnet.net` is slow or unreachable.
