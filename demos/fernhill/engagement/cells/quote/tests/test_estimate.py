"""The calculator's interface, `job-spec`: what a quote promises, whatever the constants are."""

import unittest

import estimate

JOB = {"cabinets": 14, "range": "standard", "worktop_material": "laminate", "worktop_m": 5.0}


class JobSpec(unittest.TestCase):
    def test_price_is_cost_plus_35_percent_to_ten_pounds(self):
        for job in (JOB, {**JOB, "range": "premium", "worktop_material": "quartz", "worktop_m": 7.3}):
            p = estimate.price(job)
            self.assertEqual(p % 10, 0)
            self.assertAlmostEqual(p, estimate.cost(job) * 1.35, delta=5.0)

    def test_the_margin_is_the_firms(self):
        self.assertEqual(estimate.MARGIN, 0.35)

    def test_more_cabinets_or_worktop_never_costs_less(self):
        c = estimate.cost(JOB)
        self.assertGreater(estimate.cost({**JOB, "cabinets": 15}), c)
        self.assertGreater(estimate.cost({**JOB, "worktop_m": 5.5}), c)

    def test_premium_and_quartz_cost_more(self):
        c = estimate.cost(JOB)
        self.assertGreater(estimate.cost({**JOB, "range": "premium"}), c)
        self.assertGreater(estimate.cost({**JOB, "worktop_material": "oak"}), c)
        self.assertGreater(estimate.cost({**JOB, "worktop_material": "quartz"}),
                           estimate.cost({**JOB, "worktop_material": "oak"}))

    def test_a_job_it_cannot_price_is_refused(self):
        for bad in ({**JOB, "range": "deluxe"}, {**JOB, "worktop_material": "granite"}, {**JOB, "cabinets": 0}):
            with self.assertRaises(ValueError):
                estimate.cost(bad)

    def test_extra_fields_are_ignored(self):
        self.assertEqual(estimate.cost({**JOB, "job_id": "FK-1", "survey_date": "2026-01-05"}), estimate.cost(JOB))


if __name__ == "__main__":
    unittest.main()
