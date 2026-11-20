# License and attribution

This photometry analysis directory is distributed under the GNU General Public
License, version 3. See [COPYING](COPYING) for the license text.

`data_import.py` is the pyPhotometry utility supplied with the analysis request.
The analysis caller crops to the behavior session before filtering and fitting. The default analysis uses a 3 Hz low-pass filter and Tukey bisquare IRLS with tuning constant 1.4, following the supplied MATLAB function `IRLS_dFF.m` and the associated study. The Python implementation reports dF/F as a percentage. The exponential and ordinary least squares approaches are selectable. The optional `return_components` argument exposes the fitted reference and corrected signal. [Keevers & Jean-Richard-dit-Bressel (2025)](https://doi.org/10.1117/1.NPh.12.2.025003) · [Reference analysis code](https://github.com/philjrdb/RegressionSim)

Original pyPhotometry notice:

> Copyright (c) Thomas Akam 2018-2025. Licenced under the GNU General Public License v3.

Upstream project: <https://github.com/pyPhotometry/code>

This notice applies to this analysis directory; it does not change the licensing
of other parts of the repository. Raw recordings and generated analysis outputs
are not included.
