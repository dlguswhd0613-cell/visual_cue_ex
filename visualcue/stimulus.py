"""Generate Gabor patches and shape-masked drifting gratings without Pygame.

``cycles_per_patch`` measures carrier cycles across the patch's diameter, so
spatial frequency in cycles/pixel is ``cycles_per_patch / diameter_px``. It is
not cycles/degree of visual angle: that conversion needs display dimensions
and eye-to-screen distance. Orientation zero gives vertical stripes; 90 gives
horizontal stripes. Positive angles rotate the carrier axis towards positive
screen y (downwards). A static patch is produced for the supplied phase.
"""

from numbers import Integral, Real

import numpy as np


def square_geometry(stimulus):
    """20 degrees denotes the common diagonal, not the upright square's side."""
    diagonal_cm = 2 * stimulus["viewing_distance_cm"] * np.tan(np.deg2rad(stimulus["visual_angle_deg"]) / 2)
    diagonal_px = diagonal_cm * stimulus["screen_width_px"] / stimulus["screen_width_cm"]
    return {"angle_reference": "diagonal", "diagonal_cm": float(diagonal_cm),
            "side_cm": float(diagonal_cm / np.sqrt(2)), "diagonal_px": float(diagonal_px),
            "side_px": float(diagonal_px / np.sqrt(2))}


def _square_coverage(side_px, orientation_deg):
    """Equal-area apertures, supersampled edges, and a shared centered canvas."""
    size = int(np.ceil(side_px * np.sqrt(2))) + 2
    samples = 4
    coords = (np.arange(size * samples) + .5) / samples - size / 2
    x, y = coords[np.newaxis, :], coords[:, np.newaxis]
    angle = np.deg2rad(orientation_deg)
    u, v = x * np.cos(angle) + y * np.sin(angle), -x * np.sin(angle) + y * np.cos(angle)
    mask = (np.abs(u) <= side_px / 2) & (np.abs(v) <= side_px / 2)
    return mask.reshape(size, samples, size, samples).mean(axis=(1, 3))


class SquareGrating:
    """Identical downward-drifting carrier under 0/45-degree square apertures.

    Only the aperture rotates. Phase uses elapsed seconds, so slow frames do
    not slow the drift. Screen calibration assumes a centered, frontal eye.
    """

    def __init__(self, stimulus, background_gray):
        self.settings = stimulus
        self.background = background_gray
        side = square_geometry(stimulus)["side_px"]
        self.coverage = {reward: _square_coverage(side, angle) for reward, angle in ((1, 45), (0, 0))}
        size = self.coverage[1].shape[0]
        cm_per_pixel = stimulus["screen_width_cm"] / stimulus["screen_width_px"]
        y_cm = (np.arange(size) + .5 - size / 2) * cm_per_pixel
        self.y_degrees = np.rad2deg(np.arctan(y_cm / stimulus["viewing_distance_cm"]))

    def frame(self, rewarded, elapsed_s):
        s = self.settings
        # cos(k*y - omega*t): a bright peak moves toward increasing screen y.
        phase = 2 * np.pi * (s["spatial_frequency_cpd"] * self.y_degrees - s["temporal_frequency_hz"] * elapsed_s)
        amplitude = s["contrast"] * min(s["mean_gray"], 255 - s["mean_gray"])
        carrier = s["mean_gray"] + amplitude * np.cos(phase)
        pixels = self.background + self.coverage[rewarded] * (carrier[:, None] - self.background)
        gray = np.rint(pixels).clip(0, 255).astype(np.uint8)
        return np.repeat(gray[:, :, None], 3, axis=2)


def _finite_real(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite real number")
    value = float(value)
    if not np.isfinite(value):
        raise ValueError(f"{name} must be a finite real number")
    return value


def make_gabor(
    diameter_px: int,
    cycles_per_patch: float,
    orientation_deg: float = 0,
    contrast: float = 1,
    sigma_fraction: float = 0.2,
    background_gray: int = 128,
    phase_deg: float = 0,
) -> np.ndarray:
    """Return an RGB uint8 array of shape ``(diameter_px, diameter_px, 3)``.

    The sinusoidal carrier is weighted by a Gaussian whose standard deviation
    is ``sigma_fraction * diameter_px``. A raised-cosine taper over the outer
    10% of the radius joins the patch smoothly to the gray background. Pixels
    outside the circular aperture are exactly the background gray.

    Contrast scales the largest symmetric modulation that fits within 0..255
    about ``background_gray``. This leaves the carrier mean at the background
    and prevents clipping, including when a non-midgray background is chosen.
    On a black background, a nonnegative black-to-white carrier is blended
    into black with the same envelope; contrast scales its brightness. This
    adds luminance during the cue instead of using a zero-mean modulation.
    Pixel values describe requested display intensities; physical luminance
    and visual angles require calibration on the actual monitor.
    """
    if (
        isinstance(diameter_px, bool)
        or not isinstance(diameter_px, Integral)
        or not 16 <= diameter_px <= 4096
    ):
        raise ValueError("diameter_px must be an integer from 16 to 4096")
    diameter_px = int(diameter_px)
    if (
        isinstance(background_gray, bool)
        or not isinstance(background_gray, Integral)
        or not 0 <= background_gray <= 255
    ):
        raise ValueError("background_gray must be an integer from 0 to 255")
    background_gray = int(background_gray)
    cycles_per_patch = _finite_real("cycles_per_patch", cycles_per_patch)
    orientation_deg = _finite_real("orientation_deg", orientation_deg)
    contrast = _finite_real("contrast", contrast)
    sigma_fraction = _finite_real("sigma_fraction", sigma_fraction)
    phase_deg = _finite_real("phase_deg", phase_deg)
    if not 0 < cycles_per_patch <= diameter_px / 2:
        raise ValueError(
            "cycles_per_patch must be positive and no greater than diameter_px/2 "
            "(the pixel sampling limit)"
        )
    if not 0 <= contrast <= 1:
        raise ValueError("contrast must be from 0 to 1")
    if not 0 < sigma_fraction <= 0.5:
        raise ValueError("sigma_fraction must be positive and no greater than 0.5")

    if contrast == 0 or background_gray == 255:
        return np.full((diameter_px, diameter_px, 3), background_gray, dtype=np.uint8)

    # Pixel centers are symmetric about the geometric center for odd and even
    # image sizes. float32 avoids large working arrays for large displays.
    coords = np.arange(diameter_px, dtype=np.float32) - (diameter_px - 1) / 2
    x = coords[np.newaxis, :]
    y = coords[:, np.newaxis]
    radius = np.hypot(x, y)
    aperture_radius = diameter_px / 2
    sigma = sigma_fraction * diameter_px
    envelope = np.exp(-0.5 * np.square(radius / sigma))
    edge_position = np.clip(
        (radius - 0.9 * aperture_radius) / (0.1 * aperture_radius), 0, 1
    )
    envelope *= 0.5 * (1 + np.cos(np.pi * edge_position))
    envelope[radius >= aperture_radius] = 0

    theta = np.deg2rad(orientation_deg % 360)
    phase = np.deg2rad(phase_deg % 360)
    carrier_axis = x * np.cos(theta) + y * np.sin(theta)
    carrier = np.cos(2 * np.pi * (cycles_per_patch / diameter_px) * carrier_axis + phase)
    amplitude = contrast * min(background_gray, 255 - background_gray)
    if background_gray == 0:
        gray = np.rint(contrast * 127.5 * envelope * (1 + carrier))
    else:
        gray = np.rint(background_gray + amplitude * envelope * carrier)
    gray = np.clip(gray, 0, 255).astype(np.uint8)
    return np.repeat(gray[:, :, np.newaxis], 3, axis=2)
