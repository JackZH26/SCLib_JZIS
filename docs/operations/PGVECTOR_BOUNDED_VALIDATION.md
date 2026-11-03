# Bounded full projection readback

The first actual full-corpus validation on the owned restore spilled about
8.8 GB into temporary files. Its wide full join carried both vector copies for
all 1,183,943 members. This crossed the 210 GiB disk stop line. The host guard
raised before stopping the child, so the exact owned backend was separately
cancelled; temporary files were released and the projection remained sealed.
No validation or activation was committed, and production was unchanged.

Revision `0114_bounded_validation_v3` retains the original v2 function and
changes only the validation INSERT trigger to a versioned implementation. All
builder-role, per-build fence, physical catalog, seal, graph, source hash and
receipt checks remain. The complete ID inventory is counted using narrow rows;
binary vectors and origin records are compared per sealed content partition.
A lateral indexed lookup prevents each small partition from hashing the whole
projection. Every partition is visited, every actual source is accounted for,
and all partition manifests are independently recomputed. Missing/extra IDs,
corrupt final-part vectors and mismatched declared counts reject validation.
There is no sample-based or prefix-only acceptance.

The function limits its working memory to 32 MB and disables parallel query
workers. These settings are scoped to the function and restored on exit. Actual
whole-corpus elapsed time, temporary-file usage and host capacity must still be
measured; passing small fixtures does not prove capacity. The operator labels
its validation backend so a host guard can cancel only that owned task. All
exceptions in the private host guard must cancel the owned long query and stop
the child before propagating failure.

Empty downgrade restores the retained v2 trigger without deleting or rewriting
validation history. It does not establish that the previous unbounded validator
is suitable for the production disk budget. Production remains on its original
schema until the full migration and recovery gates are completed.
