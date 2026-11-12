# 0004. Zero-Cost Multi-Provider LLM Factory, Local ONNX Embeddings, and Resilient Free Web Search

Status: accepted

We decouple model inference behind a provider factory (`LLM_PROVIDER=groq|gemini|ollama|openai`) defaulting to free-tier cloud APIs (Groq `llama-3.3-70b-versatile` or Google AI Studio `gemini-2.5-flash`) and local `Ollama`, paired with local CPU ONNX embeddings (`ChromaDB` default `all-MiniLM-L6-v2`) and zero-key web search (`duckduckgo-search` backed by `open-meteo.com` for weather and `frankfurter.app` for FX rates). This guarantees a $0.00 development and evaluation cost without requiring paid API keys for embeddings or search, prevents DuckDuckGo container IP rate-limiting from breaking Test Scenarios #2 and #7, and still allows evaluators to plug in `OPENAI_API_KEY` if preferred.
