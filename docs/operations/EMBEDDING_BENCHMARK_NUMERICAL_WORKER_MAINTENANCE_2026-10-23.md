# Numerical-preserving benchmark worker maintenance source

This dedicated worker source is based on `801672a6bd8bf02416a642734e05a27071333c49`.
It retains the released v1.2 benchmark contracts, entrypoints, bounded file checks and
runtime-file metadata optimization, while restoring the exact accepted HOST_L2 module
bytes. The three numerical implementation pins remain `3487cae0…`, `440d7406…` and
`f667e54d…`; the model family and numerical runtime must not be reidentified to admit
the unrelated generic ranking refactor.

The nonnumerical mixed-profile ranking adaptation belongs to the existing similarity
context service and now lives there as a small typed function. It uses the same scalar
cosine function and exact identity tie key as the legacy ranker. The bounded population
is represented as ordered tuples and sorted in `O(n log n)` time and `O(n)` space;
parity tests protect full-score and identity ordering for accepted and mixed profiles.
There is no new dependency, registry, protocol, cache or persistence boundary.

This is a coherent separate maintenance release, not a production/API rollback.
Source validation and a wheel build do not admit a native installation, authorize a
benchmark Job, run a model or activate a device. The orchestrator still validates the
exact request, installation receipts and worker release before dispatch. The native
backend independently validates actual imported implementation pins; the pre-login
comparison below detects a mismatch before allocating another execution. Production
CPU owners and their fixed prefix remain unchanged.

The v1.2 unit's import overlay selects a whole package, not only its entrypoint. Before
requesting a fresh operator login, compare `observed_embedding_implementation_pins()`
from that exact interpreter/overlay with both pinned numerical runtimes. This function
reads the three protected implementation modules and does not import ML libraries.
