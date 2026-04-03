# shared

This directory is for code that is truly shared by multiple services.

Keep it small at first.

Good candidates:

- environment loading
- settings management
- DB connection helpers
- date formatting helpers
- generic validation
- generic utility functions

Do not move attendance-only business logic here just to force reuse.
