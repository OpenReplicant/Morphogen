# The quote calculator (`Quote calculator v7.xlsx`)

*(Made up for Morphogen's demo engagement. Described by Owen, who maintains it.)*

The designer types four things: the number of cabinets, the range (Standard or Premium), the worktop material
and the worktop length in metres. The sheet works out a cost and adds the margin.

| Cell | Name | Value | What it is |
| --- | --- | --- | --- |
| B3 | Carcass, Standard | £210 | one carcass with its fittings, Lindale's price |
| B4 | Carcass, Premium | £340 | |
| B6 | Worktop, laminate | £95 / m | supplier's price per metre |
| B7 | Worktop, oak | £210 / m | |
| B8 | Worktop, quartz | £420 / m | Stonecraft's price per metre, templated and cut |
| B10 | Worktop waste | 25% | added to every worktop for offcuts and joints |
| B12 | Hours per cabinet | 5.5 | workshop and fitting labour per cabinet |
| B13 | Hours per worktop metre | 1.5 | fitting labour per metre of worktop |
| B14 | Fixed hours per job | 16 | survey, design, delivery, snagging |
| B16 | Labour rate | £32 / hour | what an hour costs us |
| B18 | Margin | 35% | added on top of the cost |

**Cost** = cabinets × carcass + worktop metres × worktop price × (1 + waste)
\+ (cabinets × hours per cabinet + worktop metres × hours per worktop metre + fixed hours) × labour rate.

**Price** = cost × (1 + margin), rounded to the nearest £10.

The constants were last changed in March 2023. Nobody compares a job's quote with what it cost afterwards; the
bookkeeper's numbers are for the whole year.
