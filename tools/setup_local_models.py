"""Compatibility wrapper.

The project no longer uses the old 2B/4B mock-development profile.
Use setup_real_models.py for the actual 9B + BGE-M3 + optional voice stack.
"""
from setup_real_models import main

if __name__ == '__main__':
    main()
