import unittest

from app.services.costing import (
    GRAMS_ACTUAL,
    GRAMS_FILENAME,
    GRAMS_MISSING,
    GRAMS_SLICER,
    MISSING_GRAMS,
    MISSING_RATE,
    RATE_MISSING,
    RATE_PROFILE,
    RATE_SPOOL,
    cost_per_gram_from_profile,
    cost_per_gram_from_spool,
    filament_line_cost,
    select_filament_rate,
    select_part_grams,
    spool_net_grams,
)


class SpoolRateTests(unittest.TestCase):
    def test_purchase_price_over_original_net_grams(self):
        # $24 paid for a 1000 g roll → $0.024 / g
        rate = cost_per_gram_from_spool(cost=24, initial_g=1000)
        self.assertAlmostEqual(rate, 0.024)
        line = filament_line_cost(94, rate)
        self.assertTrue(line["costed"])
        self.assertAlmostEqual(line["filament_cost"], 2.256)

    def test_spool_keeps_receive_price_when_profile_changes(self):
        spool_rate = cost_per_gram_from_spool(cost=24, initial_g=1000)
        profile_rate = cost_per_gram_from_profile(
            normal_price=40, filament_weight_g=1000
        )
        chosen = select_filament_rate(spool_per_g=spool_rate, profile_per_g=profile_rate)
        self.assertEqual(chosen["source"], RATE_SPOOL)
        self.assertAlmostEqual(chosen["cost_per_g"], 0.024)
        self.assertNotAlmostEqual(chosen["cost_per_g"], profile_rate)

    def test_remaining_plus_used_when_initial_missing(self):
        net = spool_net_grams(initial_g=0, remaining_g=400, consumed_g=600)
        self.assertEqual(net, 1000)
        rate = cost_per_gram_from_spool(cost=30, initial_g=0, remaining_g=400, consumed_g=600)
        self.assertAlmostEqual(rate, 0.03)


class ProfileRateTests(unittest.TestCase):
    def test_normal_cost_divided_by_spool_size(self):
        # $72 normal cost on a 3 kg profile
        rate = cost_per_gram_from_profile(normal_price=72, filament_weight_g=3000)
        self.assertAlmostEqual(rate, 0.024)
        line = filament_line_cost(48, rate)
        self.assertAlmostEqual(line["filament_cost"], 1.152)

    def test_purchase_cost_when_normal_price_missing(self):
        rate = cost_per_gram_from_profile(normal_price=0, purchase_cost=20, filament_weight_g=1000)
        self.assertAlmostEqual(rate, 0.02)

    def test_profile_used_when_no_spool(self):
        profile_rate = cost_per_gram_from_profile(normal_price=25, filament_weight_g=1000)
        chosen = select_filament_rate(spool_per_g=None, profile_per_g=profile_rate)
        self.assertEqual(chosen["source"], RATE_PROFILE)
        self.assertAlmostEqual(chosen["cost_per_g"], 0.025)


class MissingDataTests(unittest.TestCase):
    def test_missing_grams_is_not_fake_zero_cost(self):
        grams = select_part_grams(actual_used_g=0, estimate_g=0, filename_g=None)
        self.assertEqual(grams["source"], GRAMS_MISSING)
        self.assertIsNone(grams["grams"])
        rate = cost_per_gram_from_spool(cost=24, initial_g=1000)
        line = filament_line_cost(grams["grams"], rate)
        self.assertFalse(line["costed"])
        self.assertIsNone(line["filament_cost"])
        self.assertEqual(line["reason"], MISSING_GRAMS)
        self.assertNotEqual(line["filament_cost"], 0)

    def test_grams_without_price_is_not_costed(self):
        line = filament_line_cost(48, None)
        self.assertFalse(line["costed"])
        self.assertIsNone(line["filament_cost"])
        self.assertEqual(line["reason"], MISSING_RATE)

    def test_zero_rate_is_not_costed(self):
        chosen = select_filament_rate(spool_per_g=None, profile_per_g=None)
        self.assertEqual(chosen["source"], RATE_MISSING)
        line = filament_line_cost(48, chosen["cost_per_g"])
        self.assertFalse(line["costed"])
        self.assertIsNone(line["filament_cost"])


class GramsPreferenceTests(unittest.TestCase):
    def test_actual_job_grams_beat_slicer_and_filename(self):
        chosen = select_part_grams(
            actual_used_g=90,
            estimate_g=48,
            filename_g=40,
            quantity=1,
        )
        self.assertEqual(chosen["source"], GRAMS_ACTUAL)
        self.assertEqual(chosen["grams"], 90)
        rate = cost_per_gram_from_spool(cost=24, initial_g=1000)
        line = filament_line_cost(chosen["grams"], rate)
        self.assertAlmostEqual(line["filament_cost"], 2.16)

    def test_slicer_estimate_when_job_has_no_usage(self):
        chosen = select_part_grams(actual_used_g=0, estimate_g=48, filename_g=99, quantity=1)
        self.assertEqual(chosen["source"], GRAMS_SLICER)
        self.assertEqual(chosen["grams"], 48)

    def test_filename_when_slicer_missing(self):
        chosen = select_part_grams(actual_used_g=None, estimate_g=None, filename_g=48, quantity=1)
        self.assertEqual(chosen["source"], GRAMS_FILENAME)
        self.assertEqual(chosen["grams"], 48)

    def test_plate_grams_divided_by_quantity(self):
        chosen = select_part_grams(actual_used_g=None, estimate_g=48, filename_g=None, quantity=4)
        self.assertEqual(chosen["source"], GRAMS_SLICER)
        self.assertEqual(chosen["plate_grams"], 48)
        self.assertEqual(chosen["grams"], 12)
        rate = cost_per_gram_from_profile(normal_price=24, filament_weight_g=1000)
        line = filament_line_cost(chosen["grams"], rate)
        self.assertAlmostEqual(line["filament_cost"], 0.288)


if __name__ == "__main__":
    unittest.main()
