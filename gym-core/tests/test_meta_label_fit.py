"""Synthetic date boundaries for the fixed five-close meta-label experiment."""
import csv
import importlib.util
from datetime import date, timedelta
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("meta_label_fit", Path(__file__).parents[1] / "scripts/meta_label_fit.py")
fit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fit)


def feature_rows(count=80, symbols=("A", "B")):
    rows = []
    for symbol in symbols:
        for index in range(count):
            day = (date(2024, 11, 1) + timedelta(days=index)).isoformat()
            rows.append({"symbol": symbol, "day": day, **dict.fromkeys(fit.FEATURES, index / 100),
                         "label_net_fwd": (0.01 if index % 2 else -0.01) if index + 5 < count else "",
                         "label_win": index % 2 if index + 5 < count else ""})
    return rows


def write_table(path, rows):
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, rows[0])
        writer.writeheader()
        writer.writerows(rows)


def test_fitting_never_reads_a_label_ending_in_the_evaluation_period(tmp_path):
    table = tmp_path / "features.csv"
    write_table(table, feature_rows())
    train, held = fit.load(table, "2025-01-01")
    assert {row[4] for row in train} <= {row["day"] for row in feature_rows() if row["day"] < "2024-12-27"}
    assert max(row[5] for row in train) == "2024-12-31"
    assert min(row[4] for row in held) == "2025-01-01"
    assert all(row[5] < "2025-01-01" for row in train)
    assert train == sorted(train, key=lambda row: (row[4], row[3]))


def test_training_is_unchanged_when_only_held_labels_change(tmp_path):
    rows = feature_rows()
    table = tmp_path / "features.csv"
    write_table(table, rows)
    before = fit.load(table, "2025-01-01")[0]
    for row in rows:
        if row["day"] >= "2025-01-01" and row["label_net_fwd"] != "":
            row["label_net_fwd"], row["label_win"] = -100, 0
    write_table(table, rows)
    assert fit.load(table, "2025-01-01")[0] == before


def test_label_purge_uses_observed_close_dates_across_missing_days(tmp_path):
    rows = [row for row in feature_rows() if row["day"] != "2024-12-30"]
    table = tmp_path / "features.csv"
    write_table(table, rows)
    train, _ = fit.load(table, "2025-01-01")
    assert max(row[4] for row in train) == "2024-12-25"


def test_calibration_folds_are_chronological_and_purge_labels_for_all_symbols(tmp_path):
    table = tmp_path / "features.csv"
    write_table(table, feature_rows(250))
    train, _ = fit.load(table, "2025-06-01")
    folds = fit.calibration_folds(train)
    assert len(folds) == 5
    for trained, validated in folds:
        assert trained and validated
        assert max(train[index][5] for index in trained) < min(train[index][4] for index in validated)
        assert {train[index][3] for index in validated} == {"A", "B"}
        assert set(trained).isdisjoint(validated)


def test_incomplete_forward_label_tail_is_refused(tmp_path):
    table = tmp_path / "features.csv"
    rows = feature_rows()
    rows[-1]["label_net_fwd"], rows[-1]["label_win"] = 0.1, 1
    write_table(table, rows)
    with pytest.raises(ValueError, match="five-close"):
        fit.load(table, "2025-01-01")


def test_existing_receipts_are_refused_before_fitting_or_reading_data(tmp_path):
    receipts = tmp_path / "meta-label-receipts.csv"
    receipts.write_text("saved decisions", encoding="utf-8")
    with pytest.raises(SystemExit) as stopped:
        fit.main(["--table", str(tmp_path / "does-not-exist.csv"), "--receipts", str(receipts)])
    assert stopped.value.code == 2
    assert receipts.read_text(encoding="utf-8") == "saved decisions"


def test_scaling_is_fitted_inside_each_calibration_training_fold(tmp_path):
    pytest.importorskip("sklearn")
    table = tmp_path / "features.csv"
    write_table(table, feature_rows(250))
    train, _ = fit.load(table, "2025-06-01")
    model = fit.fit_model(train)
    assert "standardscaler" in model.estimator.named_steps
    assert model.cv == fit.calibration_folds(train)
    probabilities = model.predict_proba([train[-1][0]])[0]
    assert len(probabilities) == 2 and all(0 <= value <= 1 for value in probabilities)
