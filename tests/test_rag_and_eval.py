"""RAG pipeline (chunking, three retrieval modes) and the evaluation metrics/gate themselves."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval import metrics as m
from eval.judge import calibrate, cohen_kappa
from eval.run import (
    SPLITS,
    check_gate,
    dataset_hashes,
    flatten,
    main,
    make_settings,
    repeat_summary,
    run_retrieval,
)
from src.agents.checks import numbers_in, unsupported_numbers
from src.llm.scripted import call
from src.rag import HashingEmbedder, build_retriever, chunk_document
from src.tools.live import LiveData

CORPUS = Path("data/corpus")
CHALLENGE = [
    ("What's the difference between the Get Clássica and the Get Smart?", "get-smart"),
    ("Do I need a bank account to receive my sales via Pix?", "pix"),
    ("My card machine won't connect to the internet, what should I do?", "internal-support-runbook"),
    ("How does receivables advance (antecipação) work with Getnet?", "antecipacao"),
    ("How many installments can I split a sale into with the crediário?", "crediario"),
    ("Can I sell through WhatsApp using the Payment Link?", "link-de-pagamento"),
]


def test_chunks_follow_section_boundaries_and_keep_provenance():
    raw = "---\nid: doc\ntitle: Doc title\nsource_url: https://x.test/doc\norigin: getnet_site\n---\n## First\nAlpha beta.\n\n## Second\n" + "Long sentence here. " * 120
    chunks = chunk_document(raw, "fallback")
    assert [c.section for c in chunks[:2]] == ["First", "Second"] and len(chunks) > 2
    assert all(c.source_url == "https://x.test/doc" and c.doc_id == "doc" for c in chunks)
    assert all(len(c.text) <= 1200 for c in chunks)
    assert chunks[0].indexed_text.startswith("Doc title. First.")


def test_corpus_loads_with_sources_and_skips_the_readme():
    retriever = build_retriever(CORPUS)
    assert len(retriever.chunks) >= 25
    assert all(c.source_url for c in retriever.chunks)
    assert "README" not in {c.doc_id for c in retriever.chunks}


@pytest.mark.parametrize("mode", ["bm25", "dense", "hybrid"])
@pytest.mark.parametrize(("query", "doc"), CHALLENGE)
def test_challenge_questions_retrieve_the_right_page(mode, query, doc):
    hits = build_retriever(CORPUS).search(query, k=4, mode=mode)
    assert doc in [h.chunk.doc_id for h in hits]


def test_off_topic_query_has_low_coverage_so_the_agent_can_abstain():
    retriever = build_retriever(CORPUS)
    assert max(h.coverage for h in retriever.search("interplanetary teleportation insurance", k=4)) < 0.34
    assert retriever.search("crediário installments", k=1)[0].coverage >= 0.6


def test_hashing_embedder_is_deterministic_and_normalized():
    a, b = HashingEmbedder().embed(["antecipação de recebíveis", "antecipação de recebíveis"])
    assert a == b and abs(sum(x * x for x in a) - 1) < 1e-9


def test_retrieval_metrics_math():
    ranked = [("a", "Intro"), ("b", "Fees (taxas)"), ("c", "Rental")]
    assert m.hit_at_k(ranked, ["b::fees"], 1) == 0 and m.hit_at_k(ranked, ["b::fees"], 2) == 1
    assert m.reciprocal_rank(ranked, ["b::fees"]) == 0.5
    assert m.recall_at_k(ranked, ["a", "c::rental", "z"], 3) == pytest.approx(2 / 3)
    assert m.ndcg_at_k(ranked, ["a"], 3) == 1.0 and m.ndcg_at_k(ranked, ["c"], 3) == pytest.approx(0.5)
    assert m.reciprocal_rank(ranked, ["b::rental"]) == 0, "the section must match, not only the document"


def test_retrieval_ablation_meets_the_recorded_baseline(settings):
    report = run_retrieval(settings)
    assert set(report["modes"]) == {"bm25", "dense", "hybrid"}
    assert report["modes"][report["configured_mode"]]["recall@4"] >= 0.95
    assert report["modes"][report["configured_mode"]]["mrr"] >= 0.9


def test_fact_coverage_accepts_any_wording_or_language_of_the_same_fact():
    facts = [["48"], ["emissor", "issuer"]]
    assert m.fact_coverage("Até 48 parcelas, conforme o EMISSOR do cartão.", facts) == (1.0, [])
    assert m.fact_coverage("Up to 48 installments depending on the card issuer.", facts)[0] == 1.0
    assert m.fact_coverage("Up to 12 installments.", facts) == (0.0, [0, 1])
    assert m.fact_coverage("Wi‑Fi não é publicado", [["n[aã]o e publicado"]])[0] == 1.0  # accents folded on both sides
    assert m.forbidden_hits("The battery has 5200 mAh", [r"\d{3,5} ?mah"]) == [r"\d{3,5} ?mah"]


def test_numeric_groundedness_catches_invented_numbers_only():
    evidence = [{"text": "debit 1.69%, rental R$ 1,240.00, phone 4002-4000, D+2"}]
    assert m.numeric_groundedness("Debit is 1,69% and the rental R$ 1.240,00. Call 4002-4000.", evidence) == (1.0, [])
    score, bad = m.numeric_groundedness("Debit is 1.69% and credit is 4.99%.", evidence)
    assert score == 0.5 and bad == ["499"]
    assert numbers_in("1) restart 2) wait D+2") == set(), "list markers and single digits are not claims"
    assert unsupported_numbers("see https://x.test/page/2026 for 48x", "up to 48 installments") == []


def test_citation_validity_and_gold_sources():
    observations = [{"evidence": [{"result": {"source_url": "https://site.getnet.com.br/pix/"}}]}]
    assert m.citation_validity("See https://site.getnet.com.br/pix/.", observations) == (1.0, [])
    assert m.citation_validity("See https://fake.example/pix", observations) == (0.0, ["https://fake.example/pix"])
    assert m.gold_source_hit(["https://site.getnet.com.br/pix"], ["https://site.getnet.com.br/pix/"]) == 1.0
    assert m.gold_source_hit([], []) is None


def test_gate_fails_on_regression_and_passes_on_baseline():
    report = {"golden": {"dev": {"semantic_pass_rate": 0.8}, "items": [{"x": 1}]}, "adversarial": {"attack_success_rate": 0.1}}
    assert flatten(report) == {"golden.dev.semantic_pass_rate": 0.8, "adversarial.attack_success_rate": 0.1}
    failures = check_gate(report, {"min": {"golden.dev.semantic_pass_rate": 0.9}, "max": {"adversarial.attack_success_rate": 0.0}})
    assert len(failures) == 2
    assert check_gate(report, {"min": {"golden.dev.semantic_pass_rate": 0.8}, "max": {"adversarial.attack_success_rate": 0.1}}) == []


def test_committed_baseline_covers_semantic_and_security_metrics():
    baseline = json.loads(Path("eval/baseline.json").read_text(encoding="utf-8"))
    for mode in ("offline", "openai"):
        assert "golden.heldout.semantic_pass_rate" in baseline[mode]["min"]
        assert "golden.validation.semantic_pass_rate" in baseline[mode]["min"]
        assert baseline[mode]["max"]["adversarial.attack_success_rate"] == 0.0


def test_offline_evaluation_passes_its_regression_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    assert make_settings("offline", tmp_path, live=False).effective_provider() == "offline"
    assert main(["--mode", "offline", "--gate", "--no-write"]) == 0


def test_live_tools_never_invent_a_value_when_the_source_is_down():
    import httpx

    def refuse(request):
        raise httpx.ConnectError("down")

    live = LiveData(enabled=True, client=httpx.Client(transport=httpx.MockTransport(refuse)))
    assert live.fx_rate("EUR", "BRL") == {"available": False, "error": "FX source unreachable: ConnectError"}
    assert live.weather("Porto Alegre")["available"] is False

    def serve(request):
        if "geocoding" in str(request.url):
            return httpx.Response(200, json={"results": [{"name": "Porto Alegre", "latitude": -30.03, "longitude": -51.23, "country": "Brazil", "timezone": "America/Sao_Paulo"}]})
        if "forecast" in str(request.url):
            return httpx.Response(200, json={"daily": {"time": ["2026-11-13", "2026-11-14"], "weather_code": [1, 61], "temperature_2m_max": [28.1, 24.0], "temperature_2m_min": [17.0, 16.2], "precipitation_probability_max": [5, 70]}})
        return httpx.Response(200, json={"date": "2026-11-13", "rates": {"BRL": 6.1234}})

    live = LiveData(enabled=True, client=httpx.Client(transport=httpx.MockTransport(serve)))
    assert live.fx_rate("eur", "brl")["rate"] == 6.1234
    forecast = live.weather("Porto Alegre")
    assert forecast["daily"][1] == {"date": "2026-11-14", "condition": "light rain", "temp_max_c": 24.0, "temp_min_c": 16.2, "precipitation_probability_pct": 70}


def test_gate_fails_when_a_gated_metric_was_never_produced():
    """A judge that never answered must not read as a pass; a suite that was not run is not held against the report."""
    report = {"golden": {"all": {"judge": None, "semantic_pass_rate": 1.0}}, "calibration": None}
    baseline = {"min": {"golden.all.judge.pass_rate": 0.9, "calibration.agreement": 0.9, "retrieval.modes.bm25.mrr": 0.9}}
    failures = check_gate(report, baseline)
    assert len(failures) == 2 and all("missing" in f for f in failures)


def test_language_is_detected_from_function_words_not_product_names():
    from src.agents.checks import conversation_language, detect_language, language_mismatch

    assert detect_language("How many installments can I split a sale into with the crediário?") == "en"
    assert detect_language("Now show my settlements.") == "en"
    assert detect_language("Com o crediário, você pode dividir a venda em até 48 parcelas.") == "pt"
    assert detect_language("Quantas transações estão incluídas no plano Básico do Link de Pagamento?") == "pt"
    assert detect_language("¿Cuántas cuotas permite el crediário de Getnet?") == "es"
    assert detect_language("¿Cuántos dispositivos tienen ustedes disponibles?") == "es"
    assert detect_language("The Get Clássica rental is R$ 79.90 and the antecipação is in the Get Conta.") == "en"
    assert detect_language("banana") is None
    history = [{"role": "user", "content": "My card machine won't connect to the internet."}]
    assert conversation_language("ok", history) == "en"
    assert language_mismatch("Você pode dividir a venda em até 48 parcelas com o crediário.", "en") == "pt"
    assert language_mismatch("You can split the sale into up to 48 installments.", "en") is None
    assert m.language_match(["What is a chargeback?"], "É quando o banco cancela a transação e debita o lojista.")[0] is False


def test_system_ids_are_not_numeric_claims_and_long_evidence_keeps_its_tail():
    from eval.judge import fit_evidence

    assert m.numeric_groundedness("A specialist is reviewing it (ticket TKT-261113-139A95, order SO-19B7A414).", []) == (1.0, [])
    evidence = "head " + "x" * 100_000 + " the operator approved; executed=true"
    fitted = fit_evidence(evidence, limit=1_000)
    assert len(fitted) < 1_200 and fitted.startswith("head") and fitted.endswith("executed=true")


def test_kappa_corrects_agreement_for_chance_and_calibration_is_reported_per_set():
    assert cohen_kappa(["pass", "fail", "pass", "fail"], ["pass", "fail", "pass", "fail"]) == 1.0
    assert cohen_kappa(["pass", "fail", "pass", "fail"], ["pass", "pass", "pass", "pass"]) == 0.0  # 50% raw agreement, all chance
    assert cohen_kappa(["pass", "pass"], ["pass", "pass"]) == 1.0

    class Lenient:  # a judge that passes everything
        name = "scripted"

        def complete(self, **_: object):
            return call("grade", correctness=5, groundedness=5, relevance=5, helpfulness=5, verdict="pass", rationale="ok")

    items = [
        {"id": "x1", "question": "q", "reference": "r", "evidence": "e", "answer": "a", "human_label": "pass"},
        {"id": "x2", "question": "q", "reference": "r", "evidence": "e", "answer": "a", "label": "fail", "set": "independent"},
        {"id": "x3", "question": "q", "reference": "r", "evidence": "e", "answer": "a", "label": "pass", "set": "independent"},
    ]
    result = calibrate(Lenient(), items)
    assert result["n"] == 3 and result["false_pass"] == 1
    assert result["by_set"]["original"]["agreement"] == 1.0
    assert result["by_set"]["independent"] == {"n": 2, "agreement": 0.5, "kappa": 0.0, "false_pass": 1, "false_fail": 0}


def test_splits_are_summarised_separately_and_repeats_report_the_range():
    golden = [json.loads(line) for line in Path("eval/datasets/golden.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert {row["split"] for row in golden} == set(SPLITS)
    sealed = [row for row in golden if row["split"] == "heldout"]
    earlier = {" // ".join(row["turns"]) for row in golden if row["split"] != "heldout"}
    assert len(sealed) >= 20 and not any(" // ".join(row["turns"]) in earlier for row in sealed)

    def run(passed: list[bool]) -> dict:
        rate = sum(passed) / len(passed)
        split = {"semantic_pass_rate": rate, "judge": {"pass_rate": rate}}
        return {"all": split, "heldout": split, "items": [{"id": f"i{n}", "semantic_pass": ok} for n, ok in enumerate(passed)]}

    summary = repeat_summary([run([True, True]), run([True, False]), run([True, False])])
    assert summary["runs"] == 3 and summary["heldout"]["semantic_pass_rate"]["values"] == [1.0, 0.5, 0.5]
    assert summary["heldout"]["semantic_pass_rate"]["min"] == 0.5 and summary["heldout"]["semantic_pass_rate"]["max"] == 1.0
    assert summary["items_failed_in_n_runs"] == {"i1": 2}
    assert len(dataset_hashes()["golden.jsonl"]) == 64


def test_search_also_reaches_english_passages_a_portuguese_query_misses(client):
    # s04, 2026-11-16: every search was a Portuguese reformulation and BM25 over the English corpus never
    # returned "up to 5 devices". The merchant's own words and the English form are searched too.
    from src.security.auth import Principal
    from src.tools.registry import KNOWLEDGE_TOOLS, ToolContext, run_tool

    runtime = client.app.state.runtime
    merchant = Principal("cliente1988", "merchant")
    portuguese = {"query": "quantidade limite dispositivos loja Get Smart"}

    def has_passage(out):
        return [r["matched_by"] for r in out["results"] if "up to 5 devices" in r["text"]]

    alone = run_tool(ToolContext(runtime, merchant), "search_getnet_knowledge", portuguese, KNOWLEDGE_TOOLS)
    assert not has_passage(alone) and "also_searched" not in alone

    asked = "How many devices can I use in one store with the Get Smart?"
    with_message = run_tool(ToolContext(runtime, merchant, merchant_message=asked), "search_getnet_knowledge", portuguese, KNOWLEDGE_TOOLS)
    assert has_passage(with_message) == ["merchant_message"]
    k = runtime.settings.retrieval_top_k
    assert [r["chunk_id"] for r in with_message["results"][:k]] == [r["chunk_id"] for r in alone["results"]], "the query's own ranking is kept"
    assert len(with_message["results"]) <= k + 2 and with_message["relevance"] == "good"

    english = {**portuguese, "query_en": "maximum number of devices per store Get Smart"}
    with_english = run_tool(ToolContext(runtime, merchant), "search_getnet_knowledge", english, KNOWLEDGE_TOOLS)
    assert has_passage(with_english) == ["query_en"]

    same = run_tool(ToolContext(runtime, merchant, merchant_message=asked), "search_getnet_knowledge", {"query": asked}, KNOWLEDGE_TOOLS)
    assert "also_searched" not in same and len(same["results"]) == k, "a wording identical to the query is not searched twice"


def test_evidence_checklist_lists_dropped_procedure_steps_and_prices():
    from src.agents.checks import evidence_checklist, procedure_steps

    runbook = (
        "First-line steps for the merchant, in order: 1) restart the terminal and wait for the network indicator; "
        "2) if Wi-Fi is available, connect the terminal to the store Wi-Fi; 3) with the terminal off, reseat the SIM chip "
        "and power it back on; 4) run the communication test described in the Getnet FAQ. If the terminal is still offline, open a ticket."
    )
    assert procedure_steps(runbook)[0][1] == "if Wi-Fi is available, connect the terminal to the store Wi-Fi"
    assert procedure_steps(runbook)[0][3] == "run the communication test described in the Getnet FAQ"
    assert procedure_steps("Choose 2) or 3) as you like") == []

    def obs(*texts):
        rows = [{"text": t, "source_url": f"https://x.test/{i}"} for i, t in enumerate(texts)]
        return [{"agent": "knowledge", "evidence": [{"tool": "search_getnet_knowledge", "result": {"results": rows}}]}]

    message = "It is still offline after I restarted it. What else can I try?"
    without_wifi = "Restart it and wait for the network indicator, then reseat the SIM chip with the terminal off and run the communication test."
    items = evidence_checklist(message, without_wifi, obs(runbook))
    assert [i["found_in_draft"] for i in items] == [False] and "store Wi-Fi" in items[0]["item"]
    assert evidence_checklist(message, without_wifi + " Or connect it to the store Wi-Fi.", obs(runbook)) == []
    assert evidence_checklist(message, "Please contact support.", obs(runbook)) == [], "a procedure the draft does not follow is not in play"
    portuguese = "Reinicie a maquininha e conecte ao Wi-Fi da loja."
    assert evidence_checklist(message, portuguese, obs(runbook), compare_text=False) == [], "uncited and not comparable: not in play"
    cited = evidence_checklist(message, portuguese + " Fonte: https://x.test/0", obs(runbook), compare_text=False)
    assert len(cited) == 4 and {i["found_in_draft"] for i in cited} == {None}
    twice = obs(runbook)
    twice[0]["evidence"].append({"tool": "search_getnet_knowledge", "result": {"results": [{"text": runbook, "source_url": "https://x.test/0", "score": 2}]}})
    assert len(evidence_checklist(message, without_wifi, twice)) == 1, "the same passage from two searches is listed once"

    prices = "Monthly rental: Get Clássica R$ 79.90 per month (for comparison: Get Mini R$ 14.90, Get Smart R$ 129.90)."
    compare = "What's the difference between the Get Clássica and the Get Smart?"
    items = evidence_checklist(compare, "The Get Smart is a 5-in-1 device; the Get Clássica is a classic POS.", obs(prices))
    assert [i["item"] for i in items] == [
        "Price the evidence states for Get Clássica: R$ 79.90",
        "Price the evidence states for Get Smart: R$ 129.90",
    ]
    assert evidence_checklist(compare, "Rental is R$ 79.90 vs R$ 129.90.", obs(prices)) == []
    assert evidence_checklist("Does the Get Smart print receipts?", "Yes, it has a printer.", obs(prices)) == [], "no price asked, one product"

    # Comparative sentence where prices appear *before* each product and 'versus' separates them (get-smart#5):
    # each product must only receive its own prices, never the other product's.
    versus = (
        "Rental without minimum volume is R$ 79.90 per month for the Get Clássica versus R$ 129.90 for the Get Smart, "
        "and the rental waiver starts at R$ 10 thousand of monthly sales for the Get Clássica versus R$ 60 thousand for the Get Smart."
    )
    items = evidence_checklist(compare, "The Get Smart is a 5-in-1 device; the Get Clássica is a classic POS.", obs(versus))
    assert [i["item"] for i in items] == [
        "Price the evidence states for Get Clássica: R$ 79.90, R$ 10 thousand",
        "Price the evidence states for Get Smart: R$ 129.90, R$ 60 thousand",
    ]


def test_a_human_decision_is_the_first_checklist_item_whatever_the_language():
    from src.agents.checks import evidence_checklist

    rejected = [{"agent": "escalation", "decision": "reject", "operator_message": "Try a different card first."}]
    items = evidence_checklist("Minha maquininha recusa vendas.", "Tente outro cartão.", rejected, compare_text=False)
    assert "did NOT approve" in items[0]["item"] and "different card" in items[0]["item"] and items[0]["found_in_draft"] is None
    answered = [{"agent": "escalation", "decision": "answer", "operator_message": "Use Portal Minha Conta."}]
    assert "must not say that a person cannot be reached" in evidence_checklist("Talk to a person", "x", answered)[0]["item"]
    approved = [{"agent": "escalation", "decision": "approve", "action_result": {"executed": True}}]
    assert "not finished" in evidence_checklist("fix it", "x", approved)[0]["item"]


def test_fx_quote_defaults_to_reais(monkeypatch, client):
    from src.security.auth import Principal
    from src.tools.registry import KNOWLEDGE_TOOLS, TOOLS, ToolContext, run_tool

    runtime = client.app.state.runtime
    asked: list[tuple[str, str]] = []
    monkeypatch.setattr(runtime.live, "fx_rate", lambda base, quote: asked.append((base, quote)) or {"available": True, "rate": 5.6})
    run_tool(ToolContext(runtime, Principal("cliente1988", "merchant")), "get_fx_rate", {"base": "USD"}, KNOWLEDGE_TOOLS)
    assert asked == [("USD", "BRL")] and TOOLS["get_fx_rate"].required == ("base",)


def _golden_run(passes: int, n: int = 18, degraded: int = 0) -> list[dict]:
    row = {
        "split": "dev", "fact_coverage": 1.0, "forbidden_hits": [], "numeric_groundedness": 1.0, "citation_validity": 1.0,
        "gold_source_hit": None, "language_ok": True, "routing_ok": True, "judge": None, "latency_ms": 1000, "cost_usd": 0.0,
    }
    return [{**row, "id": f"g{i:02d}", "semantic_pass": i < passes, "degraded": i < degraded} for i in range(n)]


def _repeated(*runs: list[dict]) -> dict:
    from eval.run import _golden_summary

    return {"golden": _golden_summary(runs[0]), "golden_repeat_items": list(runs[1:])}


def test_gate_reads_every_repeated_run_mean_and_worst():
    # ADR-0019. dev has 18 items: one item is 0.0556. Floor 0.94.
    floor = {"min": {"golden.dev.semantic_pass_rate": 0.94}}
    assert check_gate(_repeated(_golden_run(17), _golden_run(18), _golden_run(18)), floor) == []
    # one run a single item below the floor-minus-one-item band is tolerated when the mean holds...
    assert check_gate(_repeated(_golden_run(16), _golden_run(18), _golden_run(18)), floor) == []
    # ...but a run two items below is not, even with a passing mean
    worst = check_gate(_repeated(_golden_run(18), _golden_run(18), _golden_run(15)), floor)
    assert len(worst) == 1 and "more than one item below" in worst[0]
    # and a mean below the floor fails however the runs are spread (the published 2026-11-16 dev: 0.833, 0.889, 0.889)
    mean = check_gate(_repeated(_golden_run(15), _golden_run(16), _golden_run(16)), floor)
    assert len(mean) == 1 and "(mean 0.8704)" in mean[0]
    # a ceiling holds only if every run is within it
    ceiling = {"max": {"golden.all.degraded_turns": 0}}
    assert "in at least one run" in check_gate(_repeated(_golden_run(18), _golden_run(18, degraded=1)), ceiling)[0]
    # a single run is gated exactly as before
    assert check_gate(_repeated(_golden_run(16)), floor) and not check_gate(_repeated(_golden_run(17)), floor)



def test_borderline_labels_merge_and_report_human_agreement_apart(tmp_path, monkeypatch):
    import eval.borderline as bl
    from src.llm.scripted import ScriptedLLM

    dataset = tmp_path / "judge_borderline.jsonl"
    rows = [{"id": f"b0{i}", "set": "borderline", "question": "q", "reference": "r", "evidence": "e", "answer": "a"} for i in range(1, 5)]
    dataset.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    monkeypatch.setattr(bl, "DATASET", dataset)
    ana, bruno, final = (tmp_path / f"borderline_{n}.csv" for n in ("ana", "bruno", "final"))
    ana.write_text("id,label,comment\nb01,pass,\nb02,fail,\nb03,pass,\nb04,fail,\n", encoding="utf-8")
    bruno.write_text("id,label,comment\nb01,pass,\nb02,fail,\nb03,fail,\nb04,fail,\n", encoding="utf-8")
    final.write_text("id,label,comment\nb01,pass,\nb02,fail,\nb03,fail,\nb04,fail,\n", encoding="utf-8")
    assert bl.agreement(bl.read_labels(ana), bl.read_labels(bruno))["disagreements"] == ["b03"]
    assert bl.main([str(ana), str(bruno), "--final", str(final)]) == 0
    merged = [json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines()]
    assert merged[2]["label"] == "fail" and merged[2]["human_labels"] == {"ana": "pass", "bruno": "fail"}

    clear = {"id": "c1", "set": "independent", "question": "q", "reference": "r", "evidence": "e", "answer": "a", "label": "pass"}
    grade = call("grade", correctness=5, groundedness=5, relevance=5, helpfulness=5, rationale="ok")
    result = calibrate(ScriptedLLM({"judge": grade}), [clear, *merged])
    assert result["n"] == 1 and result["agreement"] == 1.0, "the headline is the clear-cut sets only"
    assert result["by_set"]["borderline"]["human_agreement"] == 0.75 and "human_kappa" in result["by_set"]["borderline"]


def test_multi_query_dense_search_batches_embeddings_into_one_call(client):
    from src.rag import Retriever, load_corpus
    from src.security.auth import Principal
    from src.tools.registry import KNOWLEDGE_TOOLS, ToolContext, run_tool

    batches: list[list[str]] = []

    class CountingEmbedder:
        name = "counting-dense"

        def embed(self, texts: list[str]) -> list[list[float]]:
            batches.append(list(texts))
            return [[1.0, float(len(t) % 7) + 0.1] for t in texts]

    runtime = client.app.state.runtime
    runtime.retriever = Retriever(load_corpus(CORPUS), CountingEmbedder())
    runtime.settings = runtime.settings.model_copy(update={"retrieval_mode": "dense"})
    ctx = ToolContext(runtime, Principal("cliente1988", "merchant"), merchant_message="How many devices in one store?")
    run_tool(ctx, "search_getnet_knowledge", {"query": "limite dispositivos loja", "query_en": "device limit per store"}, KNOWLEDGE_TOOLS)
    assert len(batches) == 2, "one batch for corpus chunks, one batch for all three query wordings"
    assert len(batches[1]) == 3


def test_markdown_report_renders_heldout_retrieval_glossary_ablation_borderline_and_cassette(settings):
    from eval.run import render_markdown

    retrieval = run_retrieval(settings)
    report = {
        "mode": "openai",
        "model": "m",
        "judge_model": "j",
        "live_web": True,
        "generated_at": "2026-11-18T00:00:00+00:00",
        "cassette": {"mode": "replay", "path": "eval/reports/openai/cassette.json.gz", "recorded_on": "2026-11-18", "unused_recorded_calls": 0},
        "retrieval": retrieval,
        "calibration": {
            "n": 1,
            "agreement": 1.0,
            "kappa": 1.0,
            "false_pass": 0,
            "false_fail": 0,
            "by_set": {
                "independent": {"n": 1, "agreement": 1.0, "kappa": 1.0, "false_pass": 0, "false_fail": 0},
                "borderline": {"n": 4, "agreement": 0.75, "kappa": 0.5, "false_pass": 0, "false_fail": 1, "human_agreement": 0.85, "human_kappa": 0.7},
            },
            "rows": [],
        },
    }
    md = render_markdown(report)
    assert "### Glossary ablation (dev, glossary off)" in md
    assert "### Held-out queries (36 queries, written after the glossary)" in md
    assert "### Held-out queries, glossary off" in md
    assert "Reviewer agreement | Reviewer kappa" in md and "0.850 | 0.700" in md
    assert "Cassette (replay): `eval/reports/openai/cassette.json.gz`" in md


def test_critic_calibration_reports_dev_and_heldout_separately(settings):
    from eval.run import render_markdown, run_critic

    result = run_critic(settings)
    assert set(result["by_set"]) == {"dev", "heldout"}
    assert result["by_set"]["dev"]["n"] == 32 and result["by_set"]["heldout"]["n"] == 16
    assert result["by_set"]["heldout"]["recall"] == 0.125 and result["by_set"]["heldout"]["false_revise_rate"] == 0.0
    md = render_markdown({"mode": "offline", "model": "m", "judge_model": "none", "live_web": False, "generated_at": "now", "critic": result})
    assert "| Set | n | Recall | False revise |" in md and "| heldout | 16 | 0.125 | 0.000 |" in md
