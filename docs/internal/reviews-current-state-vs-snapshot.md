# Reviews: Current State vs Snapshot

## Recommendation

It is worth changing `/reviews` so the main card content shows the current effective item state from `RunItem.item_metadata`, while keeping `ReviewCorrection` and `RootCauseRevision` as immutable historical review snapshots.

This is the correct approach if `/reviews` is meant to be an operational review queue for the current labeling state.

## Why It Is Worth It

- It removes an entire class of drift bugs between run/compare and `/reviews`.
- It makes the current visible state consistent across:
  - run view
  - compare view
  - reviews page
- It preserves approval history and few-shot lineage correctly instead of trying to keep historical snapshots mutable.

## When This Bug Can Appear

This bug appears whenever current item state and review snapshot state drift apart. That is a normal workflow risk, not a rare corner case.

### Common cases

1. A review candidate is created from an incomplete patch.
   - Category is saved first.
   - Detail is saved later through a different path.
   - `RunItem.item_metadata` gets updated, but the review snapshot does not.

2. A human edits from run/compare after a review row already exists.
   - Current `RunItem.item_metadata` changes.
   - `/reviews` may still show the older review-candidate snapshot.

3. Legacy or backfilled data exists.
   - Older review rows may be missing fields that do exist on the run item.

4. Delete, reset, withdraw, or supersede flows occur.
   - Current state changes.
   - Historical review candidates remain frozen by design.

5. Any future partial-sync bug happens.
   - If one write path misses one field, `/reviews` drifts again if it renders snapshot data as the main truth.

## The Structural Issue

Right now `/reviews` is being used like a page about what the item is now, but its main card content comes from the review snapshot.

Those are different concepts:

- `RunItem.item_metadata`: current effective truth
- `ReviewCorrection` / `RootCauseRevision`: historical review record for a specific revision

As long as the main `/reviews` card renders snapshot data as if it were the current truth, this class of bugs will keep coming back.

## Safe Implementation Model

The safe implementation is:

1. Keep `ReviewCorrection` immutable in meaning.
   - It remains the pending/approved/rejected candidate tied to a specific revision.

2. Add current effective state to `/api/corrections`.
   - Example fields:
     - `current_root_cause`
     - `current_root_cause_detail`
     - `current_root_cause_note`
     - `current_solution`
     - `current_solution_note`
     - `current_root_cause_source`

3. Render the main `/reviews` card from `current_*`.
   - This keeps `/reviews`, run, and compare aligned.

4. Keep history and approval based on revision snapshots.
   - Revision history remains historical.
   - Few-shot retrieval remains based on approved active candidates, not live item state.

## What Not To Do

Do not replace the review snapshot everywhere with live `RunItem` fields.

That would create real bugs:

- approved examples would appear to change after approval
- revision history would become misleading
- review decisions would no longer point to a stable snapshot

## Conclusion

This change is worth doing because the bug is not a one-off data issue. It can appear any time current state changes after snapshot creation, which is a normal workflow in this system.

The robust model is:

- current state from `RunItem.item_metadata`
- historical review state from `ReviewCorrection` and `RootCauseRevision`

That separation fixes the product semantics instead of patching individual drift cases.
