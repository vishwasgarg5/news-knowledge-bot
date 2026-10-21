# Historical syndication audit (2026-10-21)

## Scope and safety

This is a retrospective replay of evidence already stored in three historical `data/operational_snapshot.json` revisions. It did not run the production workflow, fetch live news, alter scoring, or send Telegram messages.

The replay applies the current `app/research.py::_same_reporting_copy` rule to the saved `verification.evidence` rows in their stored order. A report is treated as a likely near-identical copy when either:
- its title shares at least 6 non-stopword tokens with Jaccard similarity >= 0.78; or
- its summary shares at least 10 non-stopword tokens with Jaccard similarity >= 0.82.

Because these historical snapshots were created before the new exclusion metric, the counts below are retrospective estimates, not recorded runtime exclusions. The original raw candidate pools are not preserved in these snapshots, so this audit cannot detect copies that were never saved as evidence.

## Results

| Snapshot date | Snapshot commit | Stories | Saved evidence rows | Likely copies within saved evidence | Affected stories |
|---|---|---:|---:|---:|---:|
| 2026-10-19 | `14f385a048bbb6a2f28a32a528c1dbd36881dbb5` | 10 | 23 | 13 | 3 |
| 2026-10-20 | `57e7c97c17fe39baf829ef4f5d9be521bfaed2d0` | 9 | 19 | 0 | 0 |
| 2026-10-21 | `8626e62e354567f7dbaf02afb74791bdbb10074f` | 10 | 5 | 0 | 0 |

The October 19 snapshot's three affected stories had 19 evidence rows reduced to 6 after sequential deduplication, while the other 4 evidence rows in that snapshot belonged to unaffected stories. Across the three affected stories specifically, 19 saved evidence rows would become 6 retained reports; the full snapshot had 23 evidence rows, 13 likely copies, and 10 retained rows overall.

### Affected stories in the October 19 snapshot

| Headline | Saved corroborating rows | Likely copies excluded retrospectively | Rows retained |
|---|---:|---:|---:|
| Trump endorses embattled Israeli Prime Minister Benjamin Netanyahu for reelection | 6 | 4 | 2 |
| Bombay HC to hear on October 26 plea filed by actor Imran Khan against ‘leave India notice’ | 5 | 2 | 3 |
| Presidential adviser says Ukraine is in talks to lift speed limit on military satellite network | 8 | 7 | 1 |

Examples of sources in likely-copy groups included TelegraphHerald.com, Nonstop Local News, Redlands Daily Facts and Euronews.com for the Netanyahu story, and multiple local outlets repeating the same report on Ukraine's military satellite network. These are algorithmic similarity flags, not a claim of proven publisher syndication.

## Interpretation

- The October 19 evidence set suggests the independent-source count could have been overstated for three stories; one would retain only one corroborating report under the current rule.
- The October 20 and 21 snapshots contain no near-identical pairs **among their saved evidence rows**. This does not prove no duplicate candidates existed, because the old snapshots do not store excluded candidates.
- Do not change production scoring based on this small retrospective sample. Use the newly added `duplicate_reporting_copies_excluded` story metric and aggregate `_stats` field during a future explicitly approved, controlled audit to measure live exclusions and compare verification coverage.
- Production decision remains HOLD pending stronger quality evidence.

## Reproducibility references

- October 19 snapshot: https://github.com/vishwasgarg5/news-knowledge-bot/blob/14f385a048bbb6a2f28a32a528c1dbd36881dbb5/data/operational_snapshot.json
- October 20 snapshot: https://github.com/vishwasgarg5/news-knowledge-bot/blob/57e7c97c17fe39baf829ef4f5d9be521bfaed2d0/data/operational_snapshot.json
- October 21 snapshot: https://github.com/vishwasgarg5/news-knowledge-bot/blob/8626e62e354567f7dbaf02afb74791bdbb10074f/data/operational_snapshot.json


## Reproduce the historical replay

From a local clone that contains the three snapshot commits, run:

```bash
python scripts/replay_syndication_audit.py
python scripts/replay_syndication_audit.py --json
```

To replay a specific revision, pass one or more explicit `DATE=GIT_SHA` values:

```bash
python scripts/replay_syndication_audit.py --revision 2026-10-19=14f385a048bbb6a2f28a32a528c1dbd36881dbb5
```

The script uses `git show` against local Git objects and the exact current detector in `app.research._same_reporting_copy`; it does not make network requests. If a historical object is not in the local clone, make that commit available through your normal Git workflow before replaying it. Unit tests use synthetic fixtures and do not require historical objects.

Regression tests:

```bash
pytest -q tests/test_syndication_replay.py
```

The report is deterministic for a given snapshot and detector version. It counts only evidence rows saved in each snapshot, so results remain retrospective estimates and cannot establish how many duplicates were present in the full candidate pool.
