"""Loads DOL LCA disclosure files into public.lca_employers. Usage: python -m pipeline.sponsorship.lca_loader"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from pipeline.db import get_conn
from pipeline.log import get_logger
from pipeline.settings import REPO_ROOT, get_settings
from pipeline.text_utils import normalize_company

LCA_DIR = REPO_ROOT / "data" / "lca"
CACHE_DIR = REPO_ROOT / "data" / "cache" / "lca"
RAW_GLOB = "LCA_*Dis*_Data_FY*.xlsx"

# DOL's typo (LCA_Dislclosure_Data...) shows up on some fiscal years' file names, hence the *Dis* glob above.
EXPECTED_COLUMNS = [
    "CASE_NUMBER",
    "CASE_STATUS",
    "VISA_CLASS",
    "EMPLOYER_NAME",
    "SOC_CODE",
    "WORKSITE_STATE",
    "TOTAL_WORKER_POSITIONS",
    "WAGE_RATE_OF_PAY_FROM",
    "WAGE_UNIT_OF_PAY",
    "DECISION_DATE",
]

WAGE_MULTIPLIER = {
    "Hour": 2080,
    "Week": 52,
    "Bi-Weekly": 26,
    "Month": 12,
    "Year": 1,
}

log = get_logger("lca_loader")


def _cache_path(path: Path) -> Path:
    stat = path.stat()
    return CACHE_DIR / f"{path.stem}_{stat.st_size}.parquet"


def _read_file(path: Path) -> pd.DataFrame:
    cache = _cache_path(path)
    if cache.exists():
        return pd.read_parquet(cache)

    df = pd.read_excel(path, engine="calamine", usecols=EXPECTED_COLUMNS)
    missing = [c for c in EXPECTED_COLUMNS if c not in df.columns]
    if missing:
        raise RuntimeError(f"{path.name} is missing expected columns: {missing}")

    df["DECISION_DATE"] = pd.to_datetime(df["DECISION_DATE"], errors="coerce")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache)
    return df


def _annualize(rate: float | None, unit: str | None) -> float | None:
    if pd.isna(rate) or pd.isna(unit):
        return None
    multiplier = WAGE_MULTIPLIER.get(str(unit).strip())
    if multiplier is None:
        return None
    return float(rate) * multiplier


def load_all() -> pd.DataFrame:
    files = sorted(LCA_DIR.glob(RAW_GLOB))
    if not files:
        raise RuntimeError(f"No LCA files found under {LCA_DIR} matching {RAW_GLOB}")

    frames = []
    print("\nPer-file DECISION_DATE range (to confirm cumulative vs. single-quarter files):")
    for path in files:
        df = _read_file(path)
        df["__source_file"] = path.name
        frames.append(df)

        date_min = df["DECISION_DATE"].min()
        date_max = df["DECISION_DATE"].max()
        min_str = date_min.date().isoformat() if pd.notna(date_min) else "?"
        max_str = date_max.date().isoformat() if pd.notna(date_max) else "?"
        print(f"  {path.name}: {len(df)} row(s), DECISION_DATE {min_str} to {max_str}")
        log.info("Read %s: %d row(s)", path.name, len(df))

    combined = pd.concat(frames, ignore_index=True)
    before = len(combined)
    combined = combined.sort_values("DECISION_DATE").drop_duplicates("CASE_NUMBER", keep="last")
    log.info(
        "Combined %d row(s) from %d file(s), %d after CASE_NUMBER dedup",
        before,
        len(files),
        len(combined),
    )
    return combined


def filter_certified_h1b(df: pd.DataFrame) -> pd.DataFrame:
    status = df["CASE_STATUS"].astype(str).str.strip().str.lower()
    visa = df["VISA_CLASS"].astype(str).str.strip().str.lower()
    return df[(status == "certified") & (visa == "h-1b")].copy()


def aggregate_by_employer(df: pd.DataFrame, relevant_soc: list[str]) -> pd.DataFrame:
    df = df.copy()
    df["employer_norm"] = df["EMPLOYER_NAME"].map(normalize_company)
    df["soc_prefix"] = df["SOC_CODE"].astype(str).str.strip().str[:7]
    df["is_relevant_soc"] = df["soc_prefix"].isin(relevant_soc)
    df["annualized_wage"] = [
        _annualize(rate, unit)
        for rate, unit in zip(df["WAGE_RATE_OF_PAY_FROM"], df["WAGE_UNIT_OF_PAY"])
    ]
    df["is_ny_nj"] = df["WORKSITE_STATE"].astype(str).str.strip().str.upper().isin(["NY", "NJ"])

    rows = []
    for employer_norm, group in df.groupby("employer_norm"):
        if not employer_norm:
            continue
        relevant = group[group["is_relevant_soc"]]
        states = sorted(
            s
            for s in group["WORKSITE_STATE"].dropna().astype(str).str.strip().str.upper().unique()
            if s
        )
        median_wage = relevant["annualized_wage"].median() if relevant["annualized_wage"].notna().any() else None
        last_decision = group["DECISION_DATE"].max()

        rows.append(
            {
                "employer_norm": employer_norm,
                "employer_raw": group["EMPLOYER_NAME"].mode().iat[0],
                "filings_total": len(group),
                "filings_relevant_soc": int(group["is_relevant_soc"].sum()),
                "positions_total": int(group["TOTAL_WORKER_POSITIONS"].fillna(0).sum()),
                "ny_nj_filings": int(group["is_ny_nj"].sum()),
                "states": states,
                "median_wage_relevant": float(median_wage) if median_wage is not None and pd.notna(median_wage) else None,
                "last_decision_date": last_decision.date() if pd.notna(last_decision) else None,
                "source_files": sorted(group["__source_file"].unique().tolist()),
            }
        )
    return pd.DataFrame(rows)


def write_employers(rows: pd.DataFrame) -> None:
    columns = (
        "employer_norm, employer_raw, filings_total, filings_relevant_soc, "
        "positions_total, ny_nj_filings, states, median_wage_relevant, "
        "last_decision_date, source_files"
    )
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("truncate table public.lca_employers")
        with cur.copy(f"copy public.lca_employers ({columns}) from stdin") as copy:
            for r in rows.itertuples(index=False):
                copy.write_row(
                    (
                        r.employer_norm,
                        r.employer_raw,
                        r.filings_total,
                        r.filings_relevant_soc,
                        r.positions_total,
                        r.ny_nj_filings,
                        r.states,
                        r.median_wage_relevant,
                        r.last_decision_date,
                        r.source_files,
                    )
                )
        conn.commit()


def main() -> None:
    settings = get_settings()
    relevant_soc = settings.search_config["lca"]["relevant_soc"]

    raw = load_all()
    certified = filter_certified_h1b(raw)
    log.info("%d certified H-1B row(s) of %d total", len(certified), len(raw))

    employers = aggregate_by_employer(certified, relevant_soc)
    write_employers(employers)
    log.info("Wrote %d employer(s) to lca_employers", len(employers))

    in_ny_nj = employers[employers["ny_nj_filings"] > 0]

    top20_relevant = in_ny_nj.sort_values("filings_relevant_soc", ascending=False).head(20)
    print("\nTop 20 NY/NJ employers by relevant-SOC filings:")
    for r in top20_relevant.itertuples(index=False):
        print(f"  {r.employer_raw:<40} relevant={r.filings_relevant_soc:<6} total={r.filings_total:<6} ny_nj={r.ny_nj_filings}")

    top20_ny_nj = in_ny_nj.sort_values("ny_nj_filings", ascending=False).head(20)
    print("\nTop 20 NY/NJ employers by NY/NJ filing count:")
    for r in top20_ny_nj.itertuples(index=False):
        print(f"  {r.employer_raw:<40} ny_nj={r.ny_nj_filings:<6} relevant={r.filings_relevant_soc:<6} total={r.filings_total}")


if __name__ == "__main__":
    main()
