# W8.6a — a provider outage is not a UI regression

Card: t_c6d66230, found by the Panel of Judges (W8.6) in `notes/poj/2026-11-18/E1.json`.

## The defect

The vision step calls an external model. Before this change the step said the
right words (`vision unreachable: gemini-3.1-flash-lite HTTP 503`) and then used
the same exit code and the same failure count as a real UI finding. The job
outcome could not tell the two apart.

Measured on run `44364221102`: every failure was `gemini-3.1-flash-lite HTTP 503`
and the run held no MISMATCH row. Measured across three runs of the same tree:
12/18, then 15/18, then 7/18 pairs matched. No code changed between them.

The cost: every red `Tests` run on the branch needed a manual read of the log to
classify it.

## The three states

| verdict | meaning | fails the job |
|---|---|---|
| `MATCH` | the model answered and the page looks complete | no |
| `DIFF` / `DISPUTED` / `FAIL` | the model answered and the page looks broken, the answer was unreadable, or the capture is missing | yes, exit 1 |
| `UNREACHABLE` | no model answered: HTTP 5xx/429, timeout, refused connection, refusal | only when most pairs are unreachable, exit 3 |

## The decision

`UNREACHABLE` alone does not fail the job. A provider outage is evidence about
the provider, not about the page. Failing on it is what made every red e2e run
ambiguous.

Two limits keep the gate real:

1. A real verdict always fails. A broken page, an unreadable answer, or a missing
   capture exits 1. The step is not decoration.
2. A run where most pairs were never judged fails with exit 3. A green check for
   a run that checked nothing is decoration of a different kind. With 18 pairs,
   up to 8 unreachable pairs stay green only if the other 10 answered and matched.

The one-line headline names the state in every case:

```
vision: 18/18 pairs MATCH - verdicts in /path
vision: 12/18 pairs MATCH, 6 UNREACHABLE - provider outage, not a UI regression (gemini-3.1-flash-lite HTTP 503 ...) - verdicts in /path
vision: UNREACHABLE - the provider answered 3/18 pairs, too few to verify the UI, so nothing was checked; this is an outage, not a regression (gemini-3.1-flash-lite HTTP 503 ...)
vision: REAL UI REGRESSION - 2/18 pairs not a MATCH (DIFF/DISPUTED/FAIL), 4 unreachable - verdicts in /path
```

The same line goes to `$GITHUB_STEP_SUMMARY`, so the job page states which of the
two happened without a log read.

Exit codes: 0 all pairs MATCH, 1 real finding, 2 cannot run (no key, no capture),
3 nothing verified.

## Retry: not added

The ladder already tries three models per pair. A second pass over the same three
models adds up to 9 minutes per pair on a blackholed connection (180 s timeout
each) inside the e2e job budget. Add backoff when a healthy provider still
returns `UNREACHABLE`. This decision has a measured trigger, not a hunch.

## What changed

- `scripts/vision_verify.py`: `vote()` tags every failure as `unreachable` or
  `answer`. `main()` counts them apart, prints the headline, writes the job
  summary, and returns exit 3 when most pairs were not judged. The comparison
  logic is unchanged.
- The provider's error body is flattened to one line before it is reported.
  Google answers with pretty-printed JSON, and the first CI run of this change
  printed that body with its newlines intact, which spread the headline over
  four log lines and broke the backticked line in the job summary.
- `VISION_API_BASE`: the provider root, overridable only to drive the test below.
  CI does not set it.
- `tests/unit/test_vision_verify.py`: drives the real script against a stub
  provider in all three states. Runs in the `unit` job.
- The step keeps its place and its real failure mode. No `continue-on-error`.

## Break-proof, both directions

The test drives the real script, so the pre-fix script is the break:

```
pre-fix script:  test_vision_verify: 3 passed, 11 failed   (all three outage cases red)
fixed script:    test_vision_verify: 14 passed, 0 failed
```

The three cases measured through `VISION_API_BASE`:

| stub answers | exit | index.json |
|---|---|---|
| 503 on every pair | 3 | 4 unreachable, 0 failed, no DIFF row |
| 503 on one pair | 0 | 1 unreachable, 3 matched |
| `broken: true` on every pair | 1 | 4 failed, 0 unreachable, headline `REAL UI REGRESSION` |
