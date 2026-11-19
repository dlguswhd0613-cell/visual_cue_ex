# License and attribution

This photometry analysis directory is distributed under the GNU General Public
License, version 3. See [COPYING](COPYING) for the license text.

`data_import.py` is the pyPhotometry utility supplied with the analysis request.
Local changes: line endings normalized to LF; optional return_components argument added to expose F0 and corrected signal. The default return and preprocessing formulas are preserved. The analysis caller crops to the behavior session before preprocessing and normalizes the corrected signal by one constant mean exponential fit across that session. An optional control_fit method adds direct filtered-control regression without exponential fitting, with a time-varying fitted-control denominator. Its original notice is preserved:

> Copyright (c) Thomas Akam 2018-2025. Licenced under the GNU General Public License v3.

Upstream project: <https://github.com/pyPhotometry/code>

This notice applies to this analysis directory; it does not change the licensing
of other parts of the repository. Raw recordings and generated analysis outputs
are not included.
