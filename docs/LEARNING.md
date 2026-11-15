# Evidence-linked memory and evaluated strategy evolution

## Four objects, not one growing chat history

**Evidence** is the bounded original output of a tool, sandbox or authorized target.
It has an ID, hash, run/task source, arguments, success flag and truncation marker.
Reading an original rechecks its stored hash. An output's presence is different
from its correctness or its relevance to the intended challenge.

**Episodes** summarize what a run actually attempted and how it terminated, retaining
references to task summaries and original evidence. They are not automatically
trusted general knowledge and do not replace the raw records.

**Memories** are structured lessons with category, procedure/negative/observation
kind, applicability conditions, steps, pitfalls and exact source citations.
They begin in quarantine (`draft`). The distiller cannot invent an evidence ID or
quote from another run. A successful procedure requires independently accepted
candidate evidence somewhere in the source run. A failure can still produce a
conditional negative lesson without being promoted to a success claim.

**Skills** are versioned conditional instructions and stop conditions used in the
native task context. A new proposal is a candidate. It does not replace the active
version just because it sounds persuasive or cites a memory.

## Distillation and review

The model distiller receives a bounded episode and selected source excerpts and
returns constrained JSON. Structural validation and citation validation happen
outside the model. Exact quotes must occur in successful/original evidence as
required by the operation. Knowledge responses, re-read outputs and model-generated
claims cannot masquerade as a new independent observation.

The stored reusable lesson body removes common flag literals, target URLs and
obvious credential forms. The original citations remain available privately for
auditing. Redaction is heuristic, not a comprehensive secrets scanner: review your
own material before importing or sharing it. Conditions and failure scopes should
be retained so a lesson does not become an unconditional attack recipe.

Content fingerprints deduplicate the normalized lesson. Source support counts
distinct challenge-input fingerprints, not repeated runs of the same input. The
smoothed support value displayed by the UI is explicitly **not a calibrated
probability that the lesson is correct**. Semantic duplicates and adapted copies of
a challenge are not perfectly identified.

An authenticated operator can review a draft, inspect its provenance and activate
or retire it. Approval creates trusted searchable knowledge; retirement removes it
from future retrieval. Existing run snapshots are not silently changed. A source
quote/hash is revalidated before approval.

## Knowledge retrieval

Reviewed documents are chunked with overlap and indexed using SQLite FTS5/BM25.
The tokenizer includes CJK bigrams so Chinese technical notes are not treated as
one undifferentiated token. It is not a language model reranker or a full semantic
Chinese segmentation system.

When an embedding model and endpoint are configured, document indexing obtains
real vectors and records their model/dimension namespace. Search can combine
lexical and cosine rankings using reciprocal rank fusion. Incompatible namespaces
are not mixed. A dense-search failure is recorded and lexical retrieval remains
available. No pseudo-embedding hashes are advertised as semantic retrieval.

Only approved documents in the run's frozen knowledge snapshot are retrieved.
Draft memories and later imports do not leak into an ongoing experiment. Retrieved
text is labeled as reference data, not a replacement for system policy or original
tool evidence. Prompt-injection resistance is not formally guaranteed.

Document indexing is a separately authorized operation that may send private text
to an external endpoint and incur charges. Query embedding calls made within a run
use that run's accounting. Import currently accepts text formats; a production
PDF/OCR/Office ingestion pipeline, provenance-aware web crawler and large curated
writeup library are not included.

## Complete autonomous cycle, after explicit authorization

`LearningCycle.execute` implements an actual chain rather than a design placeholder:

1. Require a terminal non-benchmark source episode. Reuse its valid lessons or ask
   the native distiller for them; if none are valid, stop.
2. Select one source lesson and form one conditional candidate based on its
   category's active baseline. Draft experience is permitted in this quarantined
   candidate, not in active knowledge retrieval.
3. Freeze the knowledge set and model profile configuration. Execute native
   baseline/candidate runs on the supplied held-out cases with separate exact
   answer hashes. No source-run answer is injected into the model context.
4. Evaluate the paired results. Optionally approve the source memory and promote
   the candidate only after a passing production-transport experiment. Revalidate
   citations and ensure the evaluated candidate and baseline did not change.
5. Persist the learning-cycle record, per-arm run IDs, gate reasons and promotion
   result. Keep the previous strategy available for rollback.

One cycle proposes at most one candidate to limit cost and make the change more
interpretable. It does not iterate forever or launch paid work in the background
without authorization. The UI and CLI explicitly ask for the evaluation charges.
Auto-distillation at ordinary run completion is a separate, budgeted feature; it
produces drafts, not automatically active strategies.

## Exact promotion gate

The executable evaluator requires at least three distinct category-matched cases,
with split `heldout`. Each case runs both arms, optionally 1..5 repetitions. Arm
order alternates to reduce simple order effects. An independently matched exact
answer hash determines success; manual receipts cannot affect benchmark outcomes.

A candidate can qualify only when:

- No case solved by its paired baseline regresses.
- Total solves increase, or total nonzero solves stay equal and reported token
  consumption improves by at least 10 percent.
- When configured monetary prices are known, candidate cost is not more than
  125 percent of the baseline cost.
- No uncertain billed calls make the comparison unreliable.
- The transport is a normal configured HTTP provider, not the built-in scripted
  provider or an injected test transport.

The API never accepts client-submitted "benchmark scores" as a promotion report.
Reports are created by executing the native runtime. Production HTTP transport is
not cryptographic attestation that an operator-controlled endpoint is a particular
model; the operator still controls its provider and answer keys.

Promotion checks the candidate content hash and the currently active baseline ID.
If either changed, the old evaluation is invalid for promotion. Only retired
previously active versions are eligible for rollback. Original hand-authored seed
baselines are clearly identified as initial seeds, not learned performance gains.

## Anti-contamination and research limits

Known training input fingerprints are excluded from held-out cases. Duplicate
inputs in the same suite are rejected. Benchmark episodes do not generate training
memories. Baseline/candidate use the same frozen knowledge and model configuration.
These measures reduce obvious leakage but are not enough to certify a clean
scientific benchmark: renamed/rewritten near-duplicates, answers in imported
writeups, and a provider's unknown pretraining corpus can still leak information.

Repeatedly tuning against the same hold-out set turns it into development data.
Rotate fresh validation cases and keep a final blind test set. Three cases are an
engineering safety gate, not adequate evidence of broad generalization. For a
serious comparison, use a larger licensed corpus with multiple categories,
difficulty strata, fixed model endpoints, equal budgets and repeated independent
runs. Report confidence intervals, wall time, solved fraction and monetary cost;
include ablations for retrieval, distillation and strategy updates.

Public base64 fixtures verify wiring only. A bounded three-case paired attachment evaluation exercises the promotion gate; it does not establish a general CTF advantage.
No weight training, LoRA, policy-gradient learning, model routing optimization,
self-modifying runtime code or guaranteed continual improvement is implemented.
"Evolution" here means measured versioned procedure selection, with rollback.
