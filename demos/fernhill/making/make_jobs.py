"""Write the made-up firm's job log: material/jobs.csv.

    python making/make_jobs.py

Fernhill Kitchens does not exist. This script is how its job log was made, kept so the demo can be
rebuilt and checked; it is not part of the firm's material, and the scripted engagement never
copies it (it holds the true costs the engagement has to discover). Deterministic: one seed.

What it plants, for the engagement to find:
- the quote spreadsheet's constants (material/quote-calculator.md) are out of date: carcass prices
  rose in June 2025, labour per cabinet is under-counted, and one worktop waste allowance is used for
  every material, so quoted margins drift and some jobs lose money;
- quotes are slow (survey to quote), and the slower the quote the likelier the job is lost;
- remakes follow survey measurement errors;
- final invoices go out late after a fit ends.
"""

import csv
import random
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "material" / "jobs.csv"
SEED = 20261124

LABOUR_RATE = 32.0
# The truth, which the spreadsheet does not know.
CARCASS = {"standard": (205.0, 236.0), "premium": (352.0, 371.0)}  # before and after 2025-06-01
WORKTOP = {"laminate": 95.0, "oak": 210.0, "quartz": 420.0}         # per metre, as the sheet has it
WASTE = {"laminate": 0.10, "oak": 0.16, "quartz": 0.21}
HOURS_PER_CABINET = {"standard": 6.9, "premium": 8.4}
HOURS_PER_WORKTOP_M = {"laminate": 1.1, "oak": 1.8, "quartz": 2.2}
FIXED_HOURS = 21.0
PRICE_RISE = date(2025, 6, 1)

# The spreadsheet, as material/quote-calculator.md describes it.
SHEET = dict(carcass={"standard": 210.0, "premium": 340.0}, waste=0.25, hpc=5.5, hpw=1.5,
             fixed=16.0, margin=0.35)

DESIGNERS = ["Owen", "Priya"]
SOURCES = ["website", "referral", "showroom", "houzz", "repeat"]
LOST_REASONS = ["price", "went with a quicker quote", "project postponed", "chose a national chain",
                "no reply", "went with a quicker quote", "price"]


def sheet_cost(cabinets: int, rng: str, worktop_m: float, material: str) -> float:
    s = SHEET
    return (cabinets * s["carcass"][rng]
            + worktop_m * WORKTOP[material] * (1 + s["waste"])
            + (cabinets * s["hpc"] + worktop_m * s["hpw"] + s["fixed"]) * LABOUR_RATE)


def main() -> None:
    r = random.Random(SEED)
    rows = []
    day = date(2025, 1, 6)
    n = 0
    while day < date(2026, 10, 1):
        day += timedelta(days=r.choice([2, 3, 4, 5, 6, 7, 8]))
        n += 1
        job = f"FK-{1000 + n}"
        cabinets = r.randint(8, 26)
        rng = "premium" if r.random() < 0.35 else "standard"
        material = r.choices(["laminate", "oak", "quartz"], [0.45, 0.2, 0.35])[0]
        worktop_m = round(r.uniform(2.4, 9.5), 1)
        survey = day + timedelta(days=r.randint(3, 12))
        designer = r.choice(DESIGNERS)
        # Quotes wait for Owen or Priya to rebuild the sheet by hand; busier months are slower.
        busy = 1.0 + 0.5 * (survey.month in (3, 4, 9, 10))
        lag = max(2, round(r.lognormvariate(2.05, 0.45) * busy))
        quote_sent = survey + timedelta(days=lag)
        cost = sheet_cost(cabinets, rng, worktop_m, material)
        price = round(cost * (1 + SHEET["margin"]), -1)
        row = dict(job_id=job, enquiry_date=day, source=r.choice(SOURCES), designer=designer,
                   survey_date=survey, quote_sent_date=quote_sent, cabinets=cabinets, range=rng,
                   worktop_material=material, worktop_m=worktop_m, quoted_price=price)
        p_win = max(0.08, 0.78 - 0.035 * lag)
        if quote_sent > date(2026, 9, 20):
            row.update(outcome="pending")
            rows.append(row)
            continue
        if r.random() >= p_win:
            row.update(outcome="lost", lost_reason=r.choice(LOST_REASONS if lag > 9 else LOST_REASONS[:1] + LOST_REASONS[2:]))
            rows.append(row)
            continue
        deposit = quote_sent + timedelta(days=r.randint(2, 20))
        planned = deposit + timedelta(days=r.randint(28, 56))
        slip = 0 if r.random() < 0.55 else r.randint(1, 12)
        fit_start = planned + timedelta(days=slip)
        fit_days = max(3, round(cabinets / 4 + r.uniform(0, 3)))
        fit_end = fit_start + timedelta(days=fit_days)
        carcass = CARCASS[rng][0 if survey < PRICE_RISE else 1]
        materials = (cabinets * carcass * r.uniform(0.97, 1.03)
                     + worktop_m * WORKTOP[material] * (1 + WASTE[material]) * r.uniform(0.95, 1.06))
        hours = (cabinets * HOURS_PER_CABINET[rng] + worktop_m * HOURS_PER_WORKTOP_M[material]
                 + FIXED_HOURS) * r.lognormvariate(0, 0.07)
        # A survey measurement error means remade cabinets: their materials and hours again.
        remakes = 0
        if r.random() < 0.22:
            remakes = r.choice([1, 1, 1, 2, 2, 3])
            materials += remakes * carcass * 1.1
            hours += remakes * HOURS_PER_CABINET[rng] * 1.3
            fit_end += timedelta(days=r.randint(3, 9))
        invoice = fit_end + timedelta(days=r.randint(2, 24))
        paid = invoice + timedelta(days=r.randint(7, 38))
        status = "complete"
        if fit_end > date(2026, 10, 31):
            status = "in progress"
        row.update(outcome="won", deposit_date=deposit, fit_planned_start=planned)
        if status == "complete":
            row.update(fit_start=fit_start, fit_end=fit_end, remade_cabinets=remakes,
                       remake_cause="survey measurement" if remakes and r.random() < 0.8 else ("damaged in delivery" if remakes else ""),
                       actual_materials=round(materials, 2), actual_labour_hours=round(hours, 1),
                       final_invoice_date=invoice,
                       paid_date=paid if paid <= date(2026, 11, 20) else "")
        else:
            row.update(fit_start=fit_start if fit_start <= date(2026, 11, 20) else "")
        rows.append(row)
    fields = ["job_id", "enquiry_date", "source", "designer", "survey_date", "quote_sent_date",
              "cabinets", "range", "worktop_material", "worktop_m", "quoted_price", "outcome",
              "lost_reason", "deposit_date", "fit_planned_start", "fit_start", "fit_end",
              "remade_cabinets", "remake_cause", "actual_materials", "actual_labour_hours",
              "final_invoice_date", "paid_date"]
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fields})
    print(f"{len(rows)} jobs -> {OUT}")


if __name__ == "__main__":
    main()
