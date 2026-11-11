"""Fixed local journal/evaluation actions shared by CLI and authenticated workbench."""
from ..adapters.run_store import load_verified_run, record_decision
from ..domain.account_observations import project_account
from ..domain.conversion import ConversionWorkload
from ..domain.market_models import decimal, fields
from ..domain.model import now_utc
from .external_journal import ExternalJournal
from .probe_budget import ProbeBudgetBook
from .reports import economic_report
from .venue_facts import VenueFactsJournal, validate_venue_fact

OPERATOR_ACTIONS = ("conversion-report", "probe-stage", "external-import", "venue-fact-import", "evidence-report", "evidence-decision", "order-page-import")


def operator_action(root, action, value, *, store="live"):
    if action == "order-page-import":
        from ..adapters.wallex_order_evidence import parse_order_page
        fields(value, "account_id observed_at kind page per_page payload")
        page = parse_order_page(value["payload"], kind=value["kind"], page=value["page"], per_page=value["per_page"])
        recorded = operator_action(root, "external-import", {"account_id": value["account_id"], "observed_at": value["observed_at"],
            "orders": [{"client_id": row["client_id"], "status": row["raw_status"], "symbol": row["symbol"], "filled": row["executed_qty"]} for row in page["orders"]]}, store=store)
        return {**page, **recorded, "origin_authenticated": False}
    if action == "conversion-report":
        fields(value, "instruction fills mark_price observed_at")
        fields(value["instruction"], "instruction_id account symbol side requested_base arrival_price fee_rate started_at deadline max_spread_bps quote_budget")
        if type(value["fills"]) is not list or len(value["fills"]) > 500:
            raise ValueError("conversion accepts at most 500 modeled fills")
        workload = ConversionWorkload(**value["instruction"])
        for row in value["fills"]:
            fields(row, "fill_id quantity price quote_fee observed_at")
            workload.observe_fake_fill(**row)
        return workload.shortfall(mark_price=value["mark_price"], observed_at=value["observed_at"])
    if action == "probe-stage":
        fields(value, "total_loss_limit quote_asset probe")
        fields(value["probe"], "probe_id kind symbol worst_case_total_loss venue_minimum_quote")
        root.mkdir(parents=True, exist_ok=True)
        with ProbeBudgetBook(root / "probe_budget.db", total_loss_limit=value["total_loss_limit"], quote_asset=value["quote_asset"]) as book:
            return book.stage(**value["probe"])
    if action == "venue-fact-import":
        record = validate_venue_fact(value)
        root.mkdir(parents=True, exist_ok=True)
        with VenueFactsJournal(root / "venue_facts.db") as journal:
            sequence = journal.record(record)
        return {"sequence": sequence, "origin_authenticated": False, "funded_authority": False}
    if action == "external-import":
        if type(value) is not dict:
            raise ValueError("manual account observation must be an object")
        fields(value, "account_id observed_at " + " ".join(k for k in ("balances", "orders", "exposure") if k in value))
        observed = project_account(value["account_id"], value["observed_at"], **{k: value.get(k) for k in ("balances", "orders", "exposure")})
        root.mkdir(parents=True, exist_ok=True)
        with ExternalJournal(root / "external_journal.db") as journal:
            count = journal.record(observed)
        return {"recorded_observations": count, "origin_authenticated": False, "funded_authority": False}
    if action in ("evidence-report", "evidence-decision"):
        fields(value, "run_id" if action == "evidence-report" else "run_id claim cap currency note")
        out = load_verified_run(root / "runs", value["run_id"], store=store)
        if action == "evidence-report":
            return {"report": economic_report(out), "funded_authority": False}
        if type(value["note"]) is not str or not 1 <= len(value["note"].strip()) <= 2000:
            raise ValueError("decision requires a bounded note")
        cap = decimal(value["cap"], "cap")
        path = record_decision(root / "runs", out, value["claim"], str(cap), value["currency"], value["note"], now_utc())
        return {"decision_file": path.name, "run_id": out["run_id"], "permission": "RECORD_ONLY_NOT_EXECUTION_AUTHORITY", "funded_authority": False}
    raise ValueError("unknown local operator action")
