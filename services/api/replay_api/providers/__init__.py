"""Provider interfaces (Protocols) + their Phase 1 local implementations.

Phase 2 (§4.2) adds `aws` implementations next to these; routes only ever see the
Protocol, so swapping is a wiring change in `main.create_app`.
"""
