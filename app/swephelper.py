"""
Swiss Ephemeris helper - ensures proper initialization
"""
import os
# CRITICAL: Set environment variable BEFORE importing swisseph
# This forces Moshier mode (built-in, no external files needed)
os.environ['SE_EPHE_PATH'] = ''

import swisseph as swe

# Additional safety - also set via function
swe.set_ephe_path('')

# Re-export everything from swisseph
__all__ = ['swe']
