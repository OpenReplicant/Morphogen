"""The quote calculator (`Quote calculator v7.xlsx`, material/quote-calculator.md) as code: a job's four inputs
in, its cost and price out. The constants are the sheet's cells, at their v7 values; the cell `quote-calculator`
may move the ones its `change` names, within bounds. MARGIN and LABOUR_RATE are the firm's, not the cell's.
"""

CARCASS_STANDARD = 210.0      # B3, pounds per carcass
CARCASS_PREMIUM = 340.0       # B4
WORKTOP_LAMINATE = 95.0       # B6, pounds per metre
WORKTOP_OAK = 210.0           # B7
WORKTOP_QUARTZ = 420.0        # B8
WORKTOP_WASTE = 0.25          # B10, one allowance for every material
HOURS_PER_CABINET = 5.5       # B12
HOURS_PER_WORKTOP_M = 1.5     # B13
FIXED_HOURS = 16.0            # B14
LABOUR_RATE = 32.0            # B16, pounds per hour
MARGIN = 0.35                 # B18, on cost

RANGES = ("standard", "premium")
MATERIALS = ("laminate", "oak", "quartz")


def cost(job: dict) -> float:
    """The cost of a job: `cabinets` (int), `range`, `worktop_material`, `worktop_m` (metres)."""
    cabinets, rng, material, metres = job["cabinets"], job["range"], job["worktop_material"], job["worktop_m"]
    if rng not in RANGES or material not in MATERIALS or cabinets < 1 or metres < 0:
        raise ValueError(f"not a job the calculator prices: {job}")
    carcass = CARCASS_PREMIUM if rng == "premium" else CARCASS_STANDARD
    worktop = {"laminate": WORKTOP_LAMINATE, "oak": WORKTOP_OAK, "quartz": WORKTOP_QUARTZ}[material]
    hours = cabinets * HOURS_PER_CABINET + metres * HOURS_PER_WORKTOP_M + FIXED_HOURS
    return cabinets * carcass + metres * worktop * (1 + WORKTOP_WASTE) + hours * LABOUR_RATE


def price(job: dict) -> float:
    """The quoted price: cost plus the margin, to the nearest ten pounds."""
    return round(cost(job) * (1 + MARGIN), -1)
