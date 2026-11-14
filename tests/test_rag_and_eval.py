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
