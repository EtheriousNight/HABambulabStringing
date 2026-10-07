"""Pure (Home Assistant free) core modules of the stringing detection pipeline.

This subpackage must not import ``homeassistant`` so that the decision logic,
the Mistral API client and the archive can be unit tested without a running
Home Assistant instance.
"""
