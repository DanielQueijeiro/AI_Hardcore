# 0003. Hybrid RAG Ingestion with Curated Getnet Corpus and Live Web Scraper

Status: accepted

The Knowledge Agent's RAG pipeline combines live HTTP scraping of `https://www.getnet.net/en` with a versioned, curated Markdown corpus covering Getnet Brazil's product catalog (*Get Clássica*, *Get Smart*, *Pix*, *Antecipação de Recebíveis*, *Crediário*, *Payment Link / WhatsApp*, and POS troubleshooting). Relying solely on live scraping of `getnet.net/en` during container startup fails to answer the challenge's product-specific test scenarios—which reference Brazilian POS models and payment products hosted on JS-rendered/WAF-protected pages—and risks container boot failures in restricted network environments.
