# The engagement

You are running a Morphogen engagement for a small firm. Its material is in `material/` (documents, a job sheet
export and an interview transcript). `material/` is the client's and stays out of git (it is in `.gitignore`):
read it, cite it, never commit it. Work only with files and Morphogen's skills and tools; there is no database.

Produce, in this project:

1. **The map** (the `map` skill): the firm as Backstage entity files, `catalog-info.yaml` and a `catalog/` folder,
   every claim carrying `morphogen.dev/evidence` with a quote copied from its source and the right line.
2. **Baselines**: a script in `analysis/` that computes, from the job sheet, the measures each opportunity is
   about, and its output kept in `analysis/`.
3. **One opportunity drafted as a cell** that the judge can judge (`change`, `run`, `better`, `score`, `tests`),
   with held-out answers outside the repository (`morphogen.local.yaml`, under the directory given as DATA below);
   then measure it, improve it (`tune` or a change on a branch) and get the judge's verdict.
4. **Options for one role** (the `catalog` skill): at least three, as `lifecycle: candidate` Components, each fact
   from the vendor's or registry's own page, quoted.
5. **`report.md`** for the firm's director: the findings with their numbers and sources, and each opportunity
   written up as an implementation project: what changes, the target and its measure, the options, what it is
   worth, the cost and the risk. Say what was measured and what was not.

There is no person to ask: the interview transcript is the interview, and you act for the operator in approving
your own branches (merge them into `main` with a message that says so). Rules go on `main` before a candidate is
judged against them. Use `morphogen status` after each step. Finish when `status` shows a verdict for your cell
and `report.md` is committed.
