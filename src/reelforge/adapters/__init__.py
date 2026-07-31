"""Platform adapters — real API publishers, used only when credentials exist.

Kept out of the default import path; `core.publish.get_publisher` imports these
lazily so the package (and tests) run without google/meta SDKs or credentials.
"""
