# Public trace excerpts and provenance

The two CSV files in this directory are deliberately tiny, deterministic
prefixes used only to exercise parsing, segmentation, liveness accounting, and
the exact recovery-epoch optimizer.  They are **not** a representative cache
benchmark, do not establish hit-rate or latency effects, and are not used to
claim production workload breadth.

## `cloudphysics-prefix.csv`

- Upstream project: `1a1a11a/libCacheSim`
- Upstream path: `data/cloudPhysicsIO.csv`
- Public URL: <https://github.com/1a1a11a/libCacheSim/blob/master/data/cloudPhysicsIO.csv>
- Upstream Git blob SHA: `fd9dd5905a58ed7d2a12bd2fb0bcefd4928d07cb`
- Selection rule: header plus the first 128 data rows, unchanged.
- Access date: 2026-09-15.
- Upstream project license: GNU General Public License v3.0.  A copy is stored
  as `libcachesim-GPL-3.0.txt`.

## `twitter-cluster015-prefix.csv`

- Upstream project: `twitter/cache-trace`
- Upstream path: `samples/2020Mar/cluster015`
- Public URL: <https://github.com/twitter/cache-trace/blob/master/samples/2020Mar/cluster015>
- Upstream Git blob SHA: `1e6095ba836de4a79da3cbf58720cd2ee5cd6efa`
- Selection rule: the first 128 rows.  The upstream sample has no header; this
  artifact adds `time,key,key_size,value_size,client_id,operation,ttl`.
- Access date: 2026-09-15.
- Upstream license: Creative Commons Attribution 4.0 International.  Attribution
  and a license link are stored in `twitter-CC-BY-4.0.txt`.

## Interpretation in this artifact

Each CloudPhysics record is treated as an update to its logical block number.
The Twitter parser keeps mutating operations only and treats each retained
record as an update to its key. The harness seals immutable log
segments, alternates sealed segments across two tiers, and marks only the
latest version of an object in each window as live.  This translation isolates
migration and recovery accounting.  It does not reconstruct the original
systems' admission, expiration, hit/miss, or storage-device semantics.
