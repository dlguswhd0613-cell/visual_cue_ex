"""Generate a circular Gabor patch without requiring a display or Pygame.

``cycles_per_patch`` measures carrier cycles across the patch's diameter, so
spatial frequency in cycles/pixel is ``cycles_per_patch / diameter_px``. It is
not cycles/degree of visual angle: that conversion needs display dimensions
and eye-to-screen distance. Orientation zero gives vertical stripes; 90 gives
horizontal stripes. Positive angles rotate the carrier axis towards positive
screen y (downwards). A static patch is produced for the supplied phase.
"""

from numbers import Integral, Real

import numpy as np


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

    if contrast == 0 or background_gray in (0, 255):
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
    gray = np.rint(background_gray + amplitude * envelope * carrier)
    gray = np.clip(gray, 0, 255).astype(np.uint8)
    return np.repeat(gray[:, :, np.newaxis], 3, axis=2)
