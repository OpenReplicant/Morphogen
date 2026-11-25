"""The engagement's baselines, from the job sheet export: one line per measure.

    python analysis/baseline.py material/jobs.csv > analysis/baseline.txt

Each line: measure, value, and how it was computed. Standard library only.
"""

import csv
import statistics as st
import sys
from datetime import date

LABOUR_RATE = 32.0  # material/quote-calculator.md, B16
MARGIN = 0.35       # B18


def d(s):
    return date.fromisoformat(s) if s else None


def main(path):
    rows = list(csv.DictReader(open(path)))
    decided = [r for r in rows if r["outcome"] in ("won", "lost")]
    lag = lambda r: (d(r["quote_sent_date"]) - d(r["survey_date"])).days
    out = []
    say = lambda k, v, how: out.append(f"{k}\t{v}\t{how}")
    say("jobs", len(rows), "rows in jobs.csv")
    say("won/lost/pending", "/".join(str(sum(r["outcome"] == o for r in rows)) for o in ("won", "lost", "pending")), "outcome")
    say("win_rate", f"{sum(r['outcome'] == 'won' for r in decided) / len(decided):.2f}", "won / (won + lost)")
    lags = [lag(r) for r in rows]
    say("quote_days_median", st.median(lags), "quote_sent_date - survey_date, calendar days, all jobs")
    say("quote_days_within_5", f"{sum(x <= 5 for x in lags) / len(lags):.2f}", "share of quotes sent within 5 days of the survey")
    for lo, hi in ((0, 5), (6, 9), (10, 14), (15, 999)):
        s = [r for r in decided if lo <= lag(r) <= hi]
        if s:
            say(f"win_rate_quote_{lo}_{hi if hi < 999 else 'plus'}_days", f"{sum(r['outcome'] == 'won' for r in s) / len(s):.2f}", f"n={len(s)}")
    lost = [r for r in rows if r["outcome"] == "lost"]
    say("lost_to_quicker_quote", sum(r["lost_reason"] == "went with a quicker quote" for r in lost), "lost_reason, of lost jobs")
    done = [r for r in rows if r["actual_materials"]]
    say("completed_with_costs", len(done), "rows with actual_materials")
    margins, cost_err, under = [], [], 0
    for r in done:
        cost = float(r["actual_materials"]) + LABOUR_RATE * float(r["actual_labour_hours"])
        price = float(r["quoted_price"])
        quoted_cost = price / (1 + MARGIN)
        margins.append((price - cost) / cost)
        cost_err.append((quoted_cost - cost) / cost)
        under += cost > quoted_cost
    say("markup_on_cost_median", f"{st.median(margins):.3f}", "(quoted_price - actual cost) / actual cost; intended 0.35")
    say("jobs_at_a_loss", sum(m < 0 for m in margins), "actual cost above quoted_price")
    say("quoted_cost_error_median", f"{st.median(cost_err):+.3f}", "(quoted_price/1.35 - actual cost) / actual cost")
    say("jobs_cost_underestimated", f"{under}/{len(done)}", "actual cost above the calculator's cost")
    shortfall = sum(float(r["quoted_price"]) / (1 + MARGIN) * MARGIN - (float(r["quoted_price"]) - float(r["actual_materials"]) - LABOUR_RATE * float(r["actual_labour_hours"])) for r in done)
    say("margin_shortfall_gbp", f"{shortfall:.0f}", "intended margin minus realised margin, summed over completed jobs")
    rem = [int(r["remade_cabinets"] or 0) for r in done]
    say("jobs_with_remakes", f"{sum(x > 0 for x in rem)}/{len(done)}", "remade_cabinets > 0")
    say("remakes_from_survey", sum(1 for r in done if r["remake_cause"] == "survey measurement"), "jobs, remake_cause")
    slips = [(d(r["fit_start"]) - d(r["fit_planned_start"])).days for r in done]
    say("fit_slipped_share", f"{sum(s > 0 for s in slips) / len(slips):.2f}", "fit_start after fit_planned_start")
    say("fit_slip_days_median_when_slipped", st.median([s for s in slips if s > 0]), "days")
    inv = [(d(r["final_invoice_date"]) - d(r["fit_end"])).days for r in done]
    say("invoice_days_median", st.median(inv), "final_invoice_date - fit_end")
    paid = [r for r in done if r["paid_date"]]
    balance = sum(float(r["quoted_price"]) * 0.6 for r in done) / len(done)
    say("balance_avg_gbp", f"{balance:.0f}", "60% of quoted_price, completed jobs")
    print("\n".join(out))


if __name__ == "__main__":
    main(sys.argv[1])
