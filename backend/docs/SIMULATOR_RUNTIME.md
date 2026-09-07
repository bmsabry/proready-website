# Simulator runtime contract

The simulator engine stays in the protected asset store and runs in V8 on the
server. This public repository contains only session transport, validation,
snapshots, and stand-in test fixtures. Do not add a real engine bundle,
calibration data, source documents, or training-scenario parameters here.

`sim_host.js` supports older bundles and current bundles through optional methods:

- `DLN.respondingBands(mode, circuit, ttrf1, machine)` supplies machine-specific
  response highlights. Older bundles retain the generic sensitivity fallback.
- `engine.setTuneBias(mode, circuit, value)` validates a manual trim against the
  total tuning window when a saved learner map is active. Without this method,
  the host clamps the bias to the selected mode's declared circuit window.
- `engine.applyMapping(points)` and `engine.clearMapping()` explicitly apply and
  remove learner-authored schedule points. Calls against an older bundle return
  a clear unsupported-version error without closing the session.

The mapping call takes one array argument, with at most 128 points. Each point
contains exactly `mode`, `ttrf1`, and `bias`; each bias object contains numeric
values for circuits scheduled in that mode. The host checks shape, finite
numbers, and tuning windows before invoking the engine. The engine validates
its temperature range, duplicate points, and complete circuit requirements
before changing the active map. Clearing takes no arguments.

Snapshots expose `mapPoints` and `mapActive` because they are the learner's own
work. Frames may expose the currently applied bias and mapping coverage. Hidden
reference/response/scenario configuration must never be added to a snapshot,
frame, deck, or event. Both initial construction and Reset create a fresh engine;
a saved map is not automatically reapplied. The client can scope explicit local
save/load to the authenticated `hello.licensed_to` identity.

Property writes and deletions reject inherited names and prototype-related
path segments. Tune edits must identify a known mode and scheduled circuit and
contain finite numeric values; the browser cannot replace a tuning object with
an arbitrary nested structure. Mapping methods do not expose a general method
invocation capability. Fuel selection accepts only a declared blend.

Focused backend checks, from `backend/` in a separate test environment:

```sh
python -m pip install -r requirements.txt pytest
python -m pytest -q tests/test_sim_engine.py tests/test_sim_host.py tests/test_deploy_auth.py
```

These checks use synthetic engines and cover WebSocket admission, new/apply/
clear/reset behavior, write limits, prototype-path rejection, session isolation,
older-engine fallback, and deployment authorization. Actual physics and
training-profile regression tests belong in the private simulator repository.
