"""Catalogue-wide local paper qualification using existing native owners.

No credentials, account calls or funded endpoints. Run with the project's Python.
"""
import argparse
import asyncio
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import csv
import html
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import threading
import time


def write(path, value, *, exclusive=False):
    if exclusive:
        with path.open("x", encoding="utf-8") as output:
            json.dump(value, output, indent=2, allow_nan=False)
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
            json.dump(value, output, indent=2, allow_nan=False)
        for attempt in range(8):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 7:
                    raise
                # Windows readers can briefly deny replacement of an open checkpoint.
                time.sleep(min(0.05 * 2**attempt,0.5))
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read(path):
    return json.loads(path.read_text("utf-8"))


def utc():
    return datetime.now(timezone.utc).isoformat()


def prepare(args):
    from gym.services.paper_campaign import historical_groups, market_universe, prospective_cases
    from gym.services.research_protocol import _engine_digest
    import gym

    rows = read(args.catalogue)["result"]["markets"]
    universe = market_universe(rows)
    previous = read(args.template)
    template = previous["groups"][0]["request"]
    groups = historical_groups(universe, template["windows"], template["scenarios"])
    for market in universe:
        if market["spot_status"] == "ELIGIBLE_SPOT":
            groups.append({"purpose":"observed-universe survey", "request":{
                "symbol":market["symbol"], "strategy":"ema-trend", "trials":[{"fast":2,"slow":5}],
                "windows":[{"from":"2026-11-06T00:00:00Z","to":"2026-11-06T05:00:00Z"}],
                "resolution":"5min", "cash":"300000000" if market["quote"] == "TMN" else "1000",
                "scenarios":[template["scenarios"][1]], "final_evaluation_id":None}})
    args.output.mkdir(parents=True, exist_ok=False)
    source = Path(gym.__file__).parent
    shutil.copytree(source, args.output / "engine/gym", ignore=shutil.ignore_patterns("__pycache__"))
    snapshot = args.snapshot.resolve()
    with snapshot.open("rb") as stream:
        snapshot_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    for index, group in enumerate(groups):
        group["index"] = index
        group["request"]["hypothesis"] = f"Catalogue-wide campaign {args.output.name}; group {index}; public snapshot {snapshot_hash}"
    margin = read(args.margin_catalogue)
    cases = [{"symbol":market["symbol"],"side":side} for market in margin["markets"] for side in ("long","short")]
    plan = {"schema":"market-campaign/1", "registered_at":utc(), "data":str(args.data.resolve()),
        "snapshot":str(snapshot), "snapshot_sha256":snapshot_hash, "engine_digest":_engine_digest(),
        "universe":universe, "groups":groups, "prospective":prospective_cases(universe),
        "margin_catalogue_id":margin["run_id"], "margin":cases,
        "planned_historical":sum(len(g["request"]["trials"])*len(g["request"]["windows"])*len(g["request"]["scenarios"]) for g in groups),
        "running_seconds":900,"wall_limit_seconds":1800,"fee_rate":"0.001","latency_ms":500,
        "scope":"Every eligible spot market uses the same matrix; current listings are not a historical listing census.",
        "funded_authority":False,"order_submitted":False}
    write(args.output / "plan.json", plan, exclusive=True)
    shutil.copyfile(args.catalogue, args.output / "spot-catalogue.json")
    shutil.copyfile(args.margin_catalogue, args.output / "margin-catalogue.json")
    print(json.dumps({"folder":str(args.output),"spot_markets":len(plan["prospective"])//2,
        "historical_attempts":plan["planned_historical"],"prospective_attempts":len(plan["prospective"]),"margin_directions":len(cases)}))


def inspect(out):
    from gym.domain.model import parse_ts
    result, inputs = out["result"], out["inputs"]
    end = result["end"]
    age = None if end is None else (parse_ts(inputs["to"]) - parse_ts(end["mark_time"])).total_seconds()
    return {"run_id":out["run_id"],"outputs_digest":out["outputs_digest"],"symbol":result["symbol"],
        "strategy":result["strategy"],"resolution":inputs["resolution"],"params":inputs["params"],
        "quote":result["quote"],"cash":result["start_cash"],"net_quote":end and end["net"],
        "fills":result["fills"],"qualified":result["qualified"],"bars":result["bars"],"mark_age_seconds":age,
        "running_at":result["session"]["running_at"],"session_state":result["session"]["state"],
        "termination_reason":result["session"]["events"][-1].get("reason"),
        "warmup_decisions":sum(row["action"] == "ABSTAIN_WARMUP" for row in result["decisions"]),
        "from":inputs["from"],"to":inputs["to"],"fee_rate":inputs["cost"]["fee_rate"],"latency_ms":inputs["cost"]["latency_ms"],
        "baselines":out["baselines"],"balances":result["balances"],"nonfills":result["nonfills"]}


def history_worker(folder, symbol):
    from gym.adapters.run_store import load_verified_run
    from gym.adapters.store import MarketDB
    from gym.services.experiment_registry import ExperimentRegistry
    from gym.services.research_protocol import _engine_digest
    from gym.domain.model import InstrumentId
    if type(symbol) is not str or InstrumentId.wallex(symbol).symbol != symbol or not symbol.isalnum():
        raise ValueError("invalid campaign market identity")
    plan = read(folder / "plan.json")
    assert _engine_digest() == plan["engine_digest"], "frozen engine changed"
    data = Path(plan["data"])
    db = MarketDB(Path(plan["snapshot"]), readonly=True)
    path = folder / "historical" / (symbol + ".json")
    assert not path.exists(), "Inspect existing market receipt before retrying"
    receipt = {"symbol":symbol,"started_at":utc(),"state":"RUNNING","groups":[],"funded_authority":False}
    write(path, receipt, exclusive=True)
    try:
        with ExperimentRegistry(data, store="live") as registry:
            for group in (group for group in plan["groups"] if group["request"]["symbol"] == symbol):
                if shutil.disk_usage(folder).free < 5 * 1024**3:
                    raise RuntimeError("Campaign paused before disk reserve is exhausted")
                outcome = registry.run(db, group["request"])["experiment"]
                results = {event["attempt_id"]:event for event in outcome["events"] if event["kind"] == "RESULT"}
                rows = []
                for attempt in (event for event in outcome["events"] if event["kind"] == "ATTEMPT"):
                    result = results.get(attempt["id"], {"state":"RESULT_PENDING"})
                    row = {"attempt_id":attempt["id"],"trial":attempt["trial"],"window":attempt["window"],
                        "scenario":attempt["scenario"],"state":result["state"],"reason":result.get("reason")}
                    if result.get("run_id"):
                        row.update(inspect(load_verified_run(data/"runs",result["run_id"],store="live")))
                    rows.append(row)
                receipt["groups"].append({"index":group["index"],"purpose":group["purpose"],"experiment_id":outcome["id"],"attempts":rows})
                write(path, receipt)
        receipt["state"] = "FINISHED"
    except Exception as error:
        receipt.update(state="INTERRUPTED_INSPECT_REGISTRY",error_type=type(error).__name__)
        raise
    finally:
        db.c.close()
        receipt["ended_at"] = utc()
        write(path, receipt)


async def watch_worker(folder, shard, shards):
    from gym.adapters.store import MarketDB
    from gym.domain.sim import CostModel
    from gym.services.live_paper import watch
    from gym.services.research_protocol import _engine_digest
    plan = read(folder / "plan.json")
    assert _engine_digest() == plan["engine_digest"], "frozen prospective engine changed"
    async def observe(index, case):
        path = folder / "prospective" / f"{index:04d}.json"
        assert not path.exists(), "A prospective attempt may not be repeated silently"
        receipt = {"index":index,"case":case,"started_at":utc(),"state":"RUNNING","funded_authority":False}
        write(path, receipt, exclusive=True)
        db = MarketDB(Path(plan["data"])/"market.db",readonly=True)
        try:
            task = asyncio.create_task(watch(db,Path(plan["data"])/"runs",case["symbol"],plan["running_seconds"],"1min",
                Decimal(case["cash"]),cost=CostModel(fee_rate=Decimal(plan["fee_rate"]),latency=timedelta(milliseconds=plan["latency_ms"])),
                strategy_id=case["strategy"],params=case["params"]))
            deadline = asyncio.get_running_loop().call_later(plan["wall_limit_seconds"],task.cancel,"Campaign wall limit reached")
            try:
                out = await task
            finally:
                deadline.cancel()
            receipt.update(inspect(out),state=out["result"]["session"]["state"])
        except Exception as error:
            receipt.update(state="FAILED",error_type=type(error).__name__)
        finally:
            db.c.close()
            receipt["ended_at"] = utc()
            write(path,receipt)
    await asyncio.gather(*(observe(index,case) for index,case in enumerate(plan["prospective"]) if index % shards == shard))


def environment():
    return {key:value for key,value in os.environ.items() if key.upper() in ("SYSTEMROOT","WINDIR","SYSTEMDRIVE","TEMP","TMP")}


def launch(args, mode):
    from gym.services.process_owner import ProcessOwner
    plan = read(args.output.resolve() / "plan.json")
    owner = "campaign-" + mode + "-" + hashlib.sha256(str(args.output.resolve()).encode()).hexdigest()[:16]
    with ProcessOwner(Path(plan["data"]), owner, store="live"):
        return _launch(args, mode)


def _launch(args, mode):
    folder = args.output.resolve()
    plan = read(folder / "plan.json")
    directory = folder / ("historical" if mode == "history" else "prospective")
    directory.mkdir(exist_ok=False)
    write(folder / (mode+"-launch.json"),{"at":utc(),"workers":args.workers,"state":"STARTED","funded_authority":False},exclusive=True)
    items = [row["symbol"] for row in plan["universe"] if row["spot_status"] == "ELIGIBLE_SPOT"] if mode == "history" else list(range(args.workers))
    stopped, lock, active = threading.Event(), threading.Lock(), set()
    def terminate(child):
        if child.poll() is None:
            child.kill()
        child.wait(timeout=5)
    def one(item):
        command = [getattr(sys,"_base_executable",sys.executable),"-I",str(Path(__file__).resolve()),"worker-"+mode,
                   "--output",str(folder),"--item",str(item),"--workers",str(args.workers),"--runtime-site",sysconfig.get_path("purelib")]
        log = folder / (mode+"-"+str(item)+".log")
        with log.open("xb") as output:
            with lock:
                if stopped.is_set():
                    return {"item":item,"state":"NOT_STARTED_OPERATOR_STOP"}
                # Use the base interpreter directly; no venv launcher survives a killed worker.
                child = subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT,env=environment())
                active.add(child)
            try:
                code = child.wait(timeout=21600 if mode == "history" else plan["wall_limit_seconds"]+120)
                return {"item":item,"state":"FINISHED" if code == 0 else "FAILED_INSPECT_RECEIPTS"}
            except subprocess.TimeoutExpired:
                terminate(child)
                return {"item":item,"state":"TIMED_OUT_INSPECT_REGISTRY"}
            except BaseException:
                terminate(child)
                raise
            finally:
                with lock:
                    active.discard(child)
    outcomes = []
    pool = ThreadPoolExecutor(max_workers=args.workers)
    pending = []
    try:
        pending = [pool.submit(one,item) for item in items]
        for future in as_completed(pending):
            outcomes.append(future.result())
            write(folder/(mode+"-progress.json"),{"finished":len(outcomes),"planned":len(items),"outcomes":outcomes,"funded_authority":False})
            print(json.dumps({"mode":mode,"finished":len(outcomes),"planned":len(items)}),flush=True)
    except BaseException:
        stopped.set()
        for future in pending:
            future.cancel()
        with lock:
            children = list(active)
        for child in children:
            terminate(child)
        write(folder/(mode+"-interrupted.json"),{"at":utc(),"completed_items":outcomes,"state":"INTERRUPTED_INSPECT_REGISTRY","funded_authority":False},exclusive=True)
        raise
    finally:
        pool.shutdown(wait=True,cancel_futures=True)
    write(folder/(mode+"-finished.json"),{"at":utc(),"outcomes":outcomes,"funded_authority":False},exclusive=True)


def margin_prepare(args):
    from gym.adapters.store import MarketDB
    from gym.domain.model import parse_ts
    from gym.services.data_portal import DataPortal
    from gym.services.margin import margin_action
    folder = args.output.resolve()
    plan = read(folder/"plan.json")
    directory = folder/"margin-previews"
    directory.mkdir(exist_ok=False)
    catalogue, next_request = None, 0.0
    for index, case in enumerate(plan["margin"]):
        path = directory/f"{index:03d}.json"
        receipt = {"index":index,**case,"started_at":utc(),"state":"REQUESTED","funded_authority":False}
        write(path,receipt,exclusive=True)
        try:
            time.sleep(max(0,next_request-time.monotonic()))
            if catalogue is None or datetime.now(timezone.utc)-parse_ts(catalogue["received_at"]) > timedelta(minutes=4):
                catalogue = margin_action(Path(plan["data"]),"margin-markets",None,store="live")
            rule = next((row for row in catalogue["markets"] if row["symbol"] == case["symbol"]),None)
            if rule is None:
                receipt["state"] = "VENUE_MARKET_REMOVED"
                continue
            db = MarketDB(Path(plan["data"])/"market.db",readonly=True)
            try:
                now = datetime.now(timezone.utc)
                quotes = DataPortal(db).tops(case["symbol"],now-timedelta(seconds=120),now)
            finally:
                db.c.close()
            from gym.domain.bars import qualified
            quotes = [quote for quote in quotes if qualified(quote)]
            if not quotes:
                receipt["state"] = "NO_FRESH_QUALIFIED_QUOTE"
                continue
            quote = quotes[-1]
            lo, hi, step = (Decimal(rule[key]) for key in ("min_risk_coef","max_risk_coef","risk_coef_step"))
            risk = lo + max(0,min(int((Decimal(2)-lo)//step),int((hi-lo)//step)))*step
            request = {"market":case["symbol"],"side":case["side"],"risk_coef":format(risk,"f"),
                "collateral":"30000000" if rule["quote"] == "TMN" else "100",
                "open_price":str(quote.ask if case["side"] == "long" else quote.bid)}
            receipt["request"] = dict(request)
            write(path,receipt)
            out = margin_action(Path(plan["data"]),"margin-preview",{"catalogue_id":catalogue["run_id"],"request":request},store="live")
            receipt["initial_receipt"] = out["run_id"]
            if out["kind"] == "COLLATERAL_LIMITS":
                request["collateral"] = str(max(Decimal(out["collateral_limits"]["min"]),min(Decimal(request["collateral"]),Decimal(out["collateral_limits"]["max"]))))
                receipt["adjusted_request"] = dict(request)
                write(path,receipt)
                out = margin_action(Path(plan["data"]),"margin-preview",{"catalogue_id":catalogue["run_id"],"request":request},store="live")
            receipt.update(state=out["kind"],receipt_id=out["run_id"],received_at=out["received_at"],request=out.get("request"))
        except Exception as error:
            receipt.update(state="PREVIEW_UNAVAILABLE",error_type=type(error).__name__,reason=str(error)[:300])
        finally:
            receipt["ended_at"] = utc()
            write(path,receipt)
            # Two calculator calls per preview, four if collateral required adjustment.
            next_request = time.monotonic()+4
    write(folder/"margin-previews-finished.json",{"at":utc(),"directions":len(plan["margin"]),"funded_authority":False},exclusive=True)


def margin_replay(args):
    from gym.services.margin import load_receipt, margin_action
    from gym.domain.model import parse_ts
    folder = args.output.resolve()
    plan = read(folder/"plan.json")
    end = datetime.now(timezone.utc)-timedelta(seconds=1)
    cases = [{"preview":read(path),"holding_seconds":seconds,"exit_fee_rate":fee}
        for path in sorted((folder/"margin-previews").glob("*.json"))
        for seconds in (120,900,3600) for fee in ("0.001","0.002")]
    write(folder/"margin-replay-plan.json",{"registered_at":utc(),"to":end.isoformat(),"cases":cases,"funded_authority":False},exclusive=True)
    rows = []
    for case in cases:
        preview = case["preview"]
        row = {"symbol":preview["symbol"],"side":preview["side"],"holding_seconds":case["holding_seconds"],"exit_fee_rate":case["exit_fee_rate"],"state":"PREVIEW_UNAVAILABLE"}
        if preview["state"] == "PREVIEW":
            saved = load_receipt(Path(plan["data"]),preview["receipt_id"],"PREVIEW")
            start = parse_ts(saved["received_at"])
            # The existing replay owner caps each source interval at 10,000 quotes.
            cutoff = min(end,start+timedelta(hours=2))
            request = {"preview_id":saved["run_id"],"from":start.isoformat(),"to":cutoff.isoformat(),"exit_fee_rate":case["exit_fee_rate"],"holding_seconds":case["holding_seconds"]}
            try:
                out = margin_action(Path(plan["data"]),"margin-replay",request,store="live")
                row.update(state=out["result"]["state"],run_id=out["run_id"],observations=out["observations"])
            except Exception as error:
                row.update(state="REPLAY_UNAVAILABLE",reason=str(error)[:300],error_type=type(error).__name__)
        rows.append(row)
        write(folder/"margin-replay-progress.json",{"rows":rows,"planned":len(cases),"funded_authority":False})
    write(folder/"margin-results.json",{"rows":rows,"states":dict(Counter(row["state"] for row in rows)),"funded_authority":False},exclusive=True)


def recover_history(args):
    """After stopping workers, reconcile committed groups and preregister explicit partial-group repeats."""
    from gym.adapters.run_store import load_verified_run
    from gym.services.experiment_registry import ExperimentRegistry
    folder = args.output.resolve()
    plan = read(folder/"plan.json")
    if not list(folder.glob("history-stop-*.json")) and not (folder/"history-interrupted.json").exists():
        raise ValueError("Stop and inspect historical workers before registering continuation")
    target = folder/"historical-continuation"
    if target.exists():
        raise ValueError("Continuation already registered; inspect its receipts")
    data = Path(plan["data"])
    groups, recovery, receipts = [], [], {}
    with ExperimentRegistry(data,store="live") as registry:
        definitions = {}
        for key, encoded in registry.conn.execute("SELECT id,body FROM events WHERE kind='EXPERIMENT'"):
            record = registry.read_record(key,encoded)
            definitions.setdefault(record["definition"]["hypothesis"],[]).append(key)
        for group in plan["groups"]:
            found = definitions.get(group["request"]["hypothesis"],[])
            if len(found) > 1:
                raise ValueError("Ambiguous native group registrations; inspect registry")
            prior = registry.read(found[0]) if found else None
            rows = []
            if prior:
                attempts = [event for event in prior["events"] if event["kind"] == "ATTEMPT"]
                results = {event["attempt_id"]:event for event in prior["events"] if event["kind"] == "RESULT"}
                for attempt in attempts:
                    result = results.get(attempt["id"],{"state":"RESULT_PENDING"})
                    row = {"attempt_id":attempt["id"],"trial":attempt["trial"],"window":attempt["window"],
                           "scenario":attempt["scenario"],"state":result["state"],"reason":result.get("reason")}
                    if result.get("run_id"):
                        row.update(inspect(load_verified_run(data/"runs",result["run_id"],store="live")))
                    rows.append(row)
                receipts.setdefault(group["request"]["symbol"],[]).append({"index":group["index"],"purpose":group["purpose"],
                    "experiment_id":prior["id"],"attempts":rows})
            expected = len(group["request"]["trials"])*len(group["request"]["windows"])*len(group["request"]["scenarios"])
            if len(rows) == expected and all(row["state"] != "RESULT_PENDING" for row in rows):
                continue
            retained = {"group":group["index"],"prior_experiment":prior and prior["id"],"prior_attempts":len(rows),
                        "prior_results":sum(row["state"] != "RESULT_PENDING" for row in rows),
                        "policy":"Partial group repeated explicitly; all prior attempts and possible orphan run files retained"}
            recovery.append(retained)
            group["request"]["hypothesis"] = f"Registered continuation of {folder.name} group {group['index']}; prior experiment {retained['prior_experiment']}"
            groups.append(group)
    target.mkdir()
    shutil.copytree(folder/"historical",target/"prior-checkpoints")
    shutil.copytree(folder/"engine",target/"engine",ignore=shutil.ignore_patterns("__pycache__"))
    for symbol, saved in receipts.items():
        write(folder/"historical"/(symbol+".json"),{"symbol":symbol,"state":"STOPPED_RECONCILED_NATIVE_REGISTRY", "groups":saved,
              "reconciled_at":utc(),"funded_authority":False})
    plan.update(registered_at=utc(),parent_campaign=str(folder),groups=groups,prospective=[],margin=[],
                planned_historical=sum(len(g["request"]["trials"])*len(g["request"]["windows"])*len(g["request"]["scenarios"]) for g in groups),
                recovery=recovery)
    write(target/"plan.json",plan,exclusive=True)
    print(json.dumps({"continuation":str(target),"groups":len(groups),"planned":plan["planned_historical"],
                      "repeated_partial_groups":sum(row["prior_experiment"] is not None for row in recovery)}))


def report(args):
    """A dated coverage snapshot, including every planned case and incomplete attempt."""
    folder = args.output.resolve()
    plan = read(folder/"plan.json")
    folders, source = [], folder
    while (source/"plan.json").exists():
        if len(folders) == 16 or source.is_symlink() or source.resolve() != source:
            raise ValueError("Continuation chain exceeds its bound or contains a redirected path")
        folders.append(source)
        source = source/"historical-continuation"
    latest, attempts = {}, []
    for source in folders:
        definition = read(source/"plan.json")
        receipts = {g["index"]:g for path in (source/"historical").glob("*.json") for g in read(path)["groups"]}
        for group in definition["groups"]:
            request = group["request"]
            saved = receipts.get(group["index"],{})
            recorded = {(r["trial"],r["window"],r["scenario"]):r for r in saved.get("attempts",[])}
            rows = []
            for trial in range(len(request["trials"])):
                for window in range(len(request["windows"])):
                    for scenario in range(len(request["scenarios"])):
                        row = {"campaign":source.name if source == folder else source.relative_to(folder).as_posix(),"group":group["index"],"symbol":request["symbol"],"strategy":request["strategy"],
                               "resolution":request["resolution"],"trial":trial,"window":window,"scenario":scenario,"state":"NOT_REPORTED"}
                        row.update(recorded.get((trial,window,scenario),{}))
                        rows.append(row)
            attempts.extend(rows)
            latest[group["index"]] = rows
    totals, market_rows = Counter(), []
    by_market = {market["symbol"]:Counter() for market in plan["universe"]}
    for rows in latest.values():
        for row in rows:
            by_market[row["symbol"]][row["state"]] += 1
    for market in plan["universe"]:
        counts = by_market[market["symbol"]]
        totals.update(counts)
        market_rows.append({**market,"planned":sum(counts.values()),"states":dict(counts)})
    cohorts = {}
    for label, source in (("original",folder),("publication-retry",folder/"prospective-retry")):
        if not (source/"plan.json").exists():
            continue
        definition = read(source/"plan.json")
        rows = []
        for index, case in enumerate(definition["prospective"]):
            path = source/"prospective"/f"{index:04d}.json"
            rows.append(read(path) if path.exists() else {"index":index,"case":case,"state":"NOT_STARTED"})
        cohorts[label] = {"states":dict(Counter(row["state"] for row in rows)),"rows":rows,"engine_digest":definition["engine_digest"]}
        if (source/"audit.json").exists():
            cohorts[label]["audit"] = read(source/"audit.json")
    margin_path = folder/"margin-results.json"
    margin = read(margin_path) if margin_path.exists() else {"state":"NOT_REPORTED"}
    preview_states = dict(Counter(read(path)["state"] for path in (folder/"margin-previews").glob("*.json")))
    retry_folder = folder/"margin-retry"
    margin_retry = {"previews":dict(Counter(read(path)["state"] for path in (retry_folder/"margin-previews").glob("*.json")))}
    if (retry_folder/"margin-results.json").exists():
        margin_retry["replays"] = read(retry_folder/"margin-results.json")
    snapshot = {"generated_at":utc(),"historical_planned":plan["planned_historical"],"historical_states":dict(totals),
                "all_registered_attempts_including_repeats":len(attempts),"markets":market_rows,"prospective":cohorts,"margin":margin,
                "margin_previews":preview_states,"margin_retry":margin_retry,
                "verification":"Worker receipts use native digest checks; no independent accounting or profitability qualification claimed",
                "funded_authority":False,"order_submitted":False}
    write(folder/"coverage.json",snapshot)
    columns = ("campaign","group","symbol","strategy","resolution","trial","window","scenario","state","run_id","reason","net_quote","fills","mark_age_seconds")
    with (folder/"results.csv").open("w",newline="",encoding="utf-8-sig") as output:
        writer = csv.DictWriter(output,columns,extrasaction="ignore")
        writer.writeheader()
        writer.writerows(attempts)
    esc = lambda value: html.escape(str(value),quote=True)
    body = "".join("<tr>"+"".join(f"<td>{esc(value)}</td>" for value in (row["symbol"],row["spot_status"],row["planned"],json.dumps(row["states"])))+"</tr>" for row in market_rows)
    summary = {"at":snapshot["generated_at"],"historical":dict(totals),"prospective":{key:value["states"] for key,value in cohorts.items()},
               "margin_previews":preview_states,"margin":margin.get("states"),"margin_retry":margin_retry.get("previews")}
    (folder/"report.html").write_text('<!doctype html><html lang="en"><meta charset="utf-8"><title>Whole-market paper coverage</title>'
        '<style>body{font:16px system-ui;max-width:1200px;margin:2rem auto;padding:1rem}td,th{padding:.4rem;text-align:left;border-bottom:1px solid #bbb}pre{white-space:pre-wrap}input{font:inherit;padding:.5rem}</style>'
        '<h1>Whole-market paper coverage</h1><p>Dated snapshot; regenerate while the campaign continues. Paper only, zero funded authority.</p>'
        '<p>NOT_REPORTED may include an in-flight or interrupted uncheckpointed group. It does not prove that no run committed. All original and repeated definitions remain in the CSV.</p>'
        '<p><a href="results.csv">All historical cases (CSV)</a> · <a href="coverage.json">Detailed outcomes and provenance (JSON)</a></p>'
        '<pre>'+esc(json.dumps(summary,indent=2))+'</pre><label>Find market <input id="find" type="search"></label>'
        '<table><thead><tr><th>Market</th><th>Venue eligibility</th><th>Planned cases</th><th>Latest group states</th></tr></thead><tbody>'+body+'</tbody></table>'
        '<script>document.getElementById("find").addEventListener("input",e=>{for(const row of document.querySelectorAll("tbody tr"))row.hidden=!row.textContent.toLowerCase().includes(e.target.value.toLowerCase())})</script></html>',encoding="utf-8")
    print(json.dumps(summary))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("prepare","history","watch","margin-prepare","margin-replay","worker-history","worker-watch","recover-history","report"))
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--data",type=Path)
    parser.add_argument("--catalogue",type=Path)
    parser.add_argument("--margin-catalogue",type=Path)
    parser.add_argument("--template",type=Path)
    parser.add_argument("--snapshot",type=Path)
    parser.add_argument("--workers",type=int,choices=range(1,9),default=6)
    parser.add_argument("--item")
    parser.add_argument("--runtime-site",type=Path)
    args = parser.parse_args()
    if args.action.startswith("worker-"):
        if args.runtime_site:
            sys.path.insert(0,str(args.runtime_site))
        sys.path.insert(0,str(args.output.resolve()/"engine"))
    if args.action == "prepare":
        if any(getattr(args,key) is None for key in ("data","catalogue","margin_catalogue","template","snapshot")):
            parser.error("prepare requires data, catalogue, margin-catalogue, template and snapshot")
        prepare(args)
    elif args.action in ("history","watch"):
        launch(args,args.action)
    elif args.action == "worker-history":
        history_worker(args.output,args.item)
    elif args.action == "worker-watch":
        asyncio.run(watch_worker(args.output,int(args.item),args.workers))
    elif args.action == "margin-prepare":
        margin_prepare(args)
    elif args.action == "recover-history":
        recover_history(args)
    elif args.action == "report":
        report(args)
    else:
        margin_replay(args)


if __name__ == "__main__":
    main()
