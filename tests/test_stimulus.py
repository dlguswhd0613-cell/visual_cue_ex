"""Display-independent checks of Gabor geometry and frequency."""

import unittest

import numpy as np

from visualcue.stimulus import make_gabor


class GaborTests(unittest.TestCase):
    def test_shape_grayscale_and_circular_background(self):
        image = make_gabor(128, 8)
        self.assertEqual(image.shape, (128, 128, 3))
        self.assertEqual(image.dtype, np.uint8)
        np.testing.assert_array_equal(image[:, :, 0], image[:, :, 1])
        np.testing.assert_array_equal(image[:, :, 0], image[:, :, 2])
        coords = np.arange(128) - 63.5
        outside = np.hypot(coords[:, None], coords[None, :]) >= 64
        self.assertTrue(np.all(image[outside] == 128))
        self.assertGreater(int(image.max()), 220)
        self.assertLess(int(image.min()), 40)

    def test_zero_contrast_and_extreme_backgrounds(self):
        for background in (0, 47, 128, 255):
            with self.subTest(background=background):
                self.assertTrue(np.all(make_gabor(64, 3, contrast=0, background_gray=background) == background))
        for background in (0, 255):
            self.assertTrue(np.all(make_gabor(64, 3, background_gray=background) == background))

    def test_frequency_has_expected_period_and_orientation(self):
        # A 160px patch with 10 cycles has 16px periods. The envelope changes
        # amplitude but not the bright/dark ordering or zero crossing sites.
        image = make_gabor(161, 161 / 16)
        row = image[80, :, 0].astype(int)
        self.assertGreater(row[80], 128)
        self.assertEqual(row[84], 128)
        self.assertLess(row[88], 128)
        self.assertEqual(row[92], 128)
        self.assertGreater(row[96], 128)
        # Zero orientation varies along x, while the center column remains
        # bright. Rotating by 90 degrees transposes the spatial structure.
        self.assertGreater(int(image[88, 80, 0]), 128)
        rotated = make_gabor(161, 161 / 16, orientation_deg=90)
        np.testing.assert_allclose(rotated, image.transpose(1, 0, 2), atol=1)

    def test_phase_reversal_and_contrast_scaling(self):
        image = make_gabor(129, 8).astype(int)
        opposite = make_gabor(129, 8, phase_deg=180).astype(int)
        half = make_gabor(129, 8, contrast=0.5).astype(int)
        np.testing.assert_allclose(image + opposite, 256, atol=1)
        np.testing.assert_allclose(half - 128, 0.5 * (image - 128), atol=1)

    def test_symmetric_bounds_for_non_midgray(self):
        image = make_gabor(129, 8, background_gray=40)
        self.assertGreaterEqual(int(image.min()), 0)
        self.assertLessEqual(int(image.max()), 80)
        self.assertEqual(int(image[64, 64, 0]), 80)

    def test_rim_fades_to_background_even_for_wide_envelope(self):
        image = make_gabor(128, 8, sigma_fraction=0.5)
        self.assertLessEqual(abs(int(image[64, 0, 0]) - 128), 2)
        self.assertLessEqual(abs(int(image[0, 64, 0]) - 128), 2)

    def test_rejects_invalid_parameters(self):
        invalid = [
            {"diameter_px": 15}, {"diameter_px": 4097},
            {"diameter_px": 64.0}, {"diameter_px": True},
            {"cycles_per_patch": 0}, {"cycles_per_patch": -1},
            {"cycles_per_patch": 33}, {"cycles_per_patch": float("nan")},
            {"cycles_per_patch": float("inf")}, {"cycles_per_patch": "4"},
            {"contrast": -0.1}, {"contrast": 1.1}, {"contrast": float("nan")},
            {"sigma_fraction": 0}, {"sigma_fraction": 0.51},
            {"background_gray": -1}, {"background_gray": 256},
            {"background_gray": 128.0}, {"background_gray": True},
            {"orientation_deg": float("inf")}, {"phase_deg": float("nan")},
        ]
        for values in invalid:
            with self.subTest(values=values):
                kwargs = {"diameter_px": 64, "cycles_per_patch": 4}
                kwargs.update(values)
                with self.assertRaises(ValueError):
                    make_gabor(**kwargs)


if __name__ == "__main__":
    unittest.main()
