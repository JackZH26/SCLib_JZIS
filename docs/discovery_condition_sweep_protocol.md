# Bounded condition sweeps

The private research-design workspace can enumerate explicit pressure and
temperature targets for one saved, anchored parent proposal. It estimates the
search size before preparing scenarios, and lets the researcher choose one to
fill an ordinary linked proposal. This is a local condition planning tool;
atomic structures, executed calculations and scientific results are not generated.

## Input and bounds

`discovery-condition-sweep/1.0.0` takes a verified research-design capability and
entry plus two closed axes. The parent must be a proposed current-head snapshot,
with an eligible retained-result or native-property baseline. Parent receipt and
safe source projection proofs are checked again. A received snapshot is not a
fresh authorization or a guarantee of subsequent server currentness.

Each axis contains 1–8 explicit choices, giving at most 64 combinations. Pressure
is specified in GPa, an ambient target (approximately 1 atm), or unspecified.
Temperature is an explicit raw value in K or unspecified. Empty axes and invalid
choices fail the whole estimate; no first-N truncation or implicit zero is used.
Raw decimals are bounded to 64 characters and must be nonnegative, finite and
representable without underflow. These are admission limits, not physical validity
limits on retained scientific data. The effective raw exponent also has to fit
the existing native private-design API's 64-bit Python Decimal representation
(`MIN_ETINY = -1999999999999999997`, `MAX_EMAX = 999999999999999999`), including
zero spellings and their fractional offset. Otherwise an axis is refused before
generation instead of preparing a target that the native design API cannot save.

Equivalent decimal aliases are compared using an exact coefficient/exponent
identity. Binary floating point is used only for finite/underflow admission, not
deduplication. Thus `10`, `10.0` and `1e1` collapse; two distinct large integers
that round to the same JavaScript number remain distinct. Ambient, specified
`0 GPa` and unspecified are separate choices; `0 K` and unspecified are separate.

The estimate reports raw and unique Cartesian counts, duplicate counts for each
axis and the finite reason codes for collapsed aliases. The first raw alias is
retained for display, while all raw input spellings remain in the input manifest.
Scenarios are ordered by normalized identity, not by a numerical ranking.

## Reproducible local manifest

Each candidate ID seals the immutable parent record SHA and the two normalized
condition identities. Reordering choices, equivalent raw aliases or renewing the
session does not change that candidate ID. This is an identity digest, not a hash
of the complete proposal bytes. Input SHA preserves the raw axes and their order;
the separate manifest SHA seals the complete output, including actor/session/grant
pins, raw values and copied user proposal content.

Source pins contain the exact baseline, context/projection digests and existing
event/state/run IDs. Source property values and raw source/context JSON are omitted.
Every scenario copies the parent's researcher hypothesis, modifications, next
action, prerequisites, anticipated outcomes and per-action budget, changing only
the requested pressure/temperature. It does not inherit measured or computed
source properties. Unknown resource totals remain unknown; estimated per-action
bounds are not summed into a fabricated batch cost.

All scientific acceptance, promotion, ML, release, calculation execution,
database-change, batch-save and atomic-site-generation flags remain false/zero.
The manifest has a four-MiB byte bound. Inputs are detached before asynchronous
proof and checksum work; scenarios own independent proposal objects.

## Selection, export and remaining persistence work

The interface estimates before generating, displays eight scenarios per window,
and provides a keyboard-accessible comparison table on wider screens. Narrow
screens stack each scenario's conditions, proposed next action and selection
button within the page width while retaining the table's accessible relationships.
Editing axes, changing the parent or actor, or leaving the page invalidates a
prepared manifest and late asynchronous results. There are no implicit choices.

Choosing a scenario only fills the existing linked-proposal form, pinning the
parent revision. It sends no POST. The researcher must reload the current baseline,
then preview and explicitly save through the existing private design API. That API
rechecks current sources, permissions and parent eligibility. The saved design
retains its exact conditions and parent; it does not retain the generation batch.
The JSON download preserves the local manifest for inspection.

This describes the initial local sweep stage. Server batch intake, durable
manifest-to-design links and history readback have since been implemented in the
[condition-batch protocol](discovery_condition_batch_protocol.md); deployed
availability still requires release verification. Atomic candidate generation needs explicit
structure revisions, sites, occupancies, species, charge/strain/interface definitions
and domain constraints. Pressure-response analysis requires comparable actual
results; these requested targets cannot serve as a measured pressure scan.
