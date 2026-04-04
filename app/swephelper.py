"""
Swiss Ephemeris helper - ensures proper initialization
"""
import os
import swisseph as swe

# Path to ephemeris files (seas_12.se1 for asteroids like Chiron)
ephe_path = os.path.join(os.path.dirname(__file__), '..', 'ephe')

if os.path.isdir(ephe_path):
    os.environ['SE_EPHE_PATH'] = ephe_path
    swe.set_ephe_path(ephe_path)
    print(f"Swiss Ephemeris path: '{ephe_path}'")
else:
    print(f"Warning: ephemeris folder not found at '{ephe_path}'")

__all__ = ['swe']
