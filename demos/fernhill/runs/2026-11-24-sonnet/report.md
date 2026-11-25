# Fernhill Kitchens: where the money goes, and what to do about it

For Sian Hollis, managing director. Prepared 24 November 2026 from the job sheet export (121 jobs that reached a survey, January 2025 to October 2026), the handbook, the tools list, the calculator description and your interview. All numbers are before VAT. Scripts and outputs are in `analysis/` (`baselines.py`, `baselines.txt`, `value_estimates.txt`); the firm is mapped in `catalog-info.yaml` and `catalog/`, each claim with a quote from your documents.

## 1. The short answer

**The leak is the quote calculator.** On the 50 won jobs that have actual costs, you charged 14.4% over what the job cost, not 35%. The sheet underestimates labour: jobs took 1.36 times the hours the calculator allows. Nothing is wrong with the margin setting. The calculator's cost is simply too low, so 35% on top of it is about 14% on top of reality. Against 35% on actual cost, the 50 jobs are about £113,000 short, roughly £2,260 a job.

**Slow quotes cost you jobs too.** The median quote leaves 6 working days after the survey, not 5. Jobs quoted within 5 working days were won 71% of the time and jobs quoted later 29%. That is an association: I could not prove slowness causes losing.

**Remakes are less common than Mark thinks**, 12% of fitted jobs and not one in five, and they are a small money item.

## 2. Findings

All from `analysis/baselines.txt` unless noted. "Actual cost" is `actual_materials` plus `actual_labour_hours` at £32 an hour, the calculator's own rate. It leaves out any overhead, and survey and design time if the timesheets do not hold it, so true margin is, if anything, lower.

| Finding | Number | Source |
| --- | --- | --- |
| Jobs, won / lost / pending | 121: 52 / 62 / 7; win rate 45.6% of decided | jobs.csv |
| The calculator reproduces every quoted price | 121 of 121 exact | my reimplementation, `calculator/` |
| Realised margin on cost, won jobs with actuals (n=50) | **14.4%** against 35% intended | quoted price against actual cost |
| Calculator cost against actual cost | 15.3% too low in total; mean absolute error 14.5% per job | |
| Actual hours against calculator hours | 1.36 times; Premium jobs 1.51 times, Standard 1.29 times | |
| Actual materials against calculator materials | 1.06 times: a 6% rise, in line with Lindale's increase | |
| Realised margin by range | Premium 10.1%, Standard 16.8% | |
| Realised margin by worktop | oak 10.1%, quartz 14.1%, laminate 16.6% | |
| Realised margin, quoted in 2025 / 2026 | 13.5% / 16.1% | |
| Jobs under 20% realised margin | 40 of 50 | |
| Quote lag, survey to quote sent (working days) | median 6, mean 7.1; 38.8% within 5 days, 11.6% within 3 | Owen median 7, Priya 6 |
| Win rate by quote lag | up to 3 days 71% (n=14); 4-5 days 71% (31); 6-8 days 39% (41); 9+ days 14% (28) | |
| Lost jobs by reason (62) | price 22, quicker quote 15, national chain 11, no reply 9, postponed 5 | |
| Quoted value of jobs lost to a quicker quote | £190,010 across 15 jobs (over 1.7 years) | |
| Remakes | 6 of 50 fitted jobs (12%); 12 cabinets; 5 survey measurement, 1 damaged in delivery | |
| Fitting started later than the whiteboard plan | 23 of 50 (46%); median 4 working days late; oak 78% late, quartz 47%, laminate 35% | |
| Fit end to final invoice | median 12.5 days, longest 23 | |
| Invoice to paid | median 24 days | |

Things the data does **not** show:
- The "one in five" remake rate (it is 12%).
- The double-bookings: two pairs at one house is in your interview only. The sheet has no record of it.
- That Owen's habits are the problem. Margins by designer are 14.8% (Owen) and 14.0% (Priya).

## 3. Opportunities as projects

### A. Reprice the calculator (done as a draft, judged)

**What changes.** Constants in `Quote calculator v7.xlsx` are replaced with values fitted to what jobs actually cost. Margin stays 35% on cost, the supplier prices and the £32 rate stay.

**Target and measure.** Mean absolute error between calculator cost and actual cost, on jobs the fitting never saw. Today 15.0%.

**What was measured.** The calculator is built as a cell (`quote-calculator`). 50 won jobs were split: 30 for practice and 20 held back outside the repository for the verdict. The judge's verdict is **pass**: error on the 20 held-out jobs fell from 15.0% to 4.5% (7 runs, sign test p = 0.008), the tests pass (price is cost x 1.35 to the nearest £10; supplier prices, £32 rate and margin fixed), and average price rises 12.2%. The change that passed was one setting: fixed hours per job 16 to 50.

**Caveats, read these.**
- 50 hours of fixed overhead is not literal. The value is the top of the range I allowed, so the search wanted more. It is covering for hours per cabinet being too low, especially on Premium (1.51 times against 1.29 times). A second round should allow range-specific hours and a wider range, and fit them to more jobs.
- Only 20 jobs sit behind the verdict.
- Raising prices will lose some jobs: 22 of 62 losses are already "price". I have not measured how win rate responds to price, and this report does not claim it.
- The reviewer found one blemish: the tuning rewrote `calculator/settings.py` and removed five explanatory comments. No scoring problem was found.
- The change is on `main` in the Python copy of the calculator. **The spreadsheet itself has not been changed.** Owen has to type the new constants in.

**Options.** (1) Fixed-hours-only fix as judged: £0, an hour of Owen's time. (2) The two-range refit above: one more session. (3) Raise the margin number: not recommended, since the bank's 35% is right and the cost under it is wrong.

**Worth.** On the 20 held-out jobs the new prices would have given about 28.5% realised margin, up from 14.6% (calculation: 1.1456 x 1.1218 - 1; not a judged number). If prices rose that way and volume held, 14 more points of margin on an average actual cost of about £10,900 is roughly £1,500 a job, or about £45,000 a year at 30 jobs. That is the ceiling. If higher prices cut wins by a third, the gain is still positive but much smaller; I cannot say how much.

**Cost.** Almost nothing in money. **Risk.** Lost jobs on price (above); a 50-hour constant that hides a pattern; staff judgement overriding the sheet.

### B. Quote within 3 working days

**What changes.** The quote is not typed up from scratch: the designer enters the four calculator inputs from the drawing and sends a templated quote the same day, with a fixed day for each survey's quote slot. Tools that quote and schedule in one place are in section 4.

**Target and measure.** Median survey-to-quote 6 working days to 3; share within 5 days 39% to 90%. Both come straight from the job sheet columns, and `baselines.py` reproduces them.

**Worth.** If the 69 decided jobs quoted after day 5 had won at the fast rate (71%) instead of 29%, that would be about 17 more wins a year. That is an upper bound: fast jobs are slightly different (40% quartz against 28%), and win rate may be tied to the customer. At half the effect, about 8 more wins a year at about £1,570 gross margin each at today's prices is **about £13,000 a year**, and more once Project A raises the margin. It is measured as an association only.

**Cost.** Mostly time. A quoting tool is £25 to £44 a user a month (section 4). **Risk.** Designers cannot quote faster because the drawing is the slow step (not measured: the sheet has no design date). Faster quotes with a stale calculator win jobs at 14% margin, so do A first.

### C. Fitting plan on a shared diary (options in section 4)

**What changes.** The whiteboard and WhatsApp plan becomes one shared calendar with a job per fitting pair, a quartz template visit booked automatically, and the "signed off" tap that tells Dee to invoice.

**Target and measure.** Share of jobs starting later than planned, 46% today (oak 78%); days from fit end to final invoice, median 12.5. Double-bookings counted from now on, since none were recorded.

**Worth.** Not measured in money. A fortnight's slip on cash is one fortnight's interest on about £8,000 outstanding at the export: small. The value is mostly avoided embarrassment and fitter time, which I could not price from the sheet.

**Cost.** Roughly £25 to £200 a month depending on the tool and the number of users (inferred from vendor list prices, section 4). **Risk.** The fitters must like it and it must run on their own Android phones; that was the condition you set. No tool has been trialled.

### D. Fewer remakes

**What changes.** Photo and dimension check on the survey, a second pair of eyes before the carcass order.

**Target.** Remake jobs per year, 3.5 today (6 jobs in 1.7 years).

**Worth.** About 7 cabinets a year plus about 24 extra hours a remake job: on the order of £4,000 a year (inferred from the average carcass price and £32 an hour). 5 of 6 remakes were measurement. **Cost** small. **Risk** low, but it is the smallest of the four.

### E. Invoice when signed off

Median 12.5 days from fit end to invoice, longest 23. Moving to same day gives about 12 days earlier cash on each of 30 jobs: a convenience, not a leak. Part of C.

## 4. Options for one role: the fitting planner

Role `job-and-fitting-planner` (`catalog/options.yaml`), requiring the interface `fitting-schedule`: jobs assigned to staff on a shared calendar, in a mobile app on Android and iPhone. Four candidates, each fact a quote from the vendor's own page (read 24 November 2026). None was trialled, so fit is by stated features only.

| Option | Price (vendor page) | Android | Xero | Notes |
| --- | --- | --- | --- | --- |
| Tradify (tradifyhq.com/uk/pricing) | £34 / £37 / £44 per user a month (Lite / Pro / Plus) | "iPhone, iPad, or Android mobile device" | "2-way sync with Xero and Sage" | month to month; per user, so 6 users on Lite is about £204 a month (my arithmetic) |
| ServiceM8 (servicem8.com/uk/pricing) | £25 / £59 / £119 a month per plan, unlimited users on paid plans | "iOS & Android apps" | accounting sync (Xero named on the homepage badge, not quoted) | the plan caps jobs a month (50 on the £25 plan), which this firm sits far under; another page of the vendor and a search listing disagreed about Android, so test on a fitter's phone first |
| Powered Now (powerednow.com/pricing) | £28 one user; £32 or £40 a user a month; excluding VAT | "iPhone, iPad and Android phone & tablet" | only Professional and above | rolling, no contract |
| Jobber (getjobber.com/pricing) | USD only; extra users $29 a month | "iOS and Android mobile apps" | "Xero" named, plan unclear | no UK price list found; least certain |

My pick for a trial, ahead of a decision: **ServiceM8 on the £25 plan**, on price, if Android holds up on a fitter's own phone; otherwise Tradify Lite. This is a recommendation to trial, not a verdict: nothing here is a judge result. The cost is within "a few hundred pounds a month".

## 5. What was measured and what was not

Measured (script output, reproducible): everything in the table in section 2; the cost-error result of the tuned calculator (judge verdict, held-out 20 jobs); the baseline of the calculator on the same jobs.

Not measured: how customers respond to higher prices; whether faster quotes cause more wins; the design time before a quote; double-bookings; the time cost of remakes beyond the timesheet hours; the vendors' tools in use; survey and design hours in the cost base. The vendor facts come from a read of their pages by a web-fetch step; I did not open the pages myself.

Method notes: the job sheet gives 50 won jobs with actuals; the 30/20 split is mine (by order in the sheet). Interview claims are quoted as Sian's. The map was merged to `main` on my own approval as the operator's stand-in (no person was available), as was the tuned calculator.

## 6. Order of work

1. Project A, second round (range-specific hours, wider range, more jobs), then Owen updates the sheet. Fastest, cheapest, largest.
2. Project B alongside it: the 3-day quote.
3. Trial a planner (C, E) for four weeks on one fitting pair's Android phones.
4. D after that if the measurement checklist shows remakes persist.
