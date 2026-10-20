# BeachWell evaluation results

Mode: **offline** (no API key; rules and hashed embeddings). Re-run with `python eval/evaluate.py`.

> Labels in `eval/data/` are placeholders written by the prototype author. Before the final report, two team members should re-label them independently and report agreement. Crunch detection, pace learning and the planner use synthetic semesters.

## A. Effort estimation (60 labeled Canvas items)

| Method | Mean abs. error (h) | Median abs. error (h) | Type accuracy | Major-deadline accuracy |
| --- | --- | --- | --- | --- |
| Constant 3 h per deadline (baseline) | 4.18 | 2.25 | 0.15 | 0.483 |
| Type keyword only (baseline) | 2.58 | 2.0 | 0.883 | 0.917 |
| BeachWell rules (title + description cues) | 1.75 | 1.0 | 0.883 | 0.933 |

## B. Finding crunch weeks (40 synthetic semesters)

Ground truth: one planted crunch week per semester (3 major deadlines in about 4 days); every semester also has a decoy week with 6 small quizzes or posts.

| Method | Precision | Recall | F1 | Decoy weeks flagged |
| --- | --- | --- | --- | --- |
| Deadline count per week (baseline, best threshold) | 0.5 | 1.0 | 0.667 | 40/40 |
| BeachWell workload score (Heavy or Overload) | 1.0 | 1.0 | 1.0 | 0/40 |

## C. Learning a student's pace (40 simulated students, 70% of tasks logged)

Mean absolute error of hour predictions, weeks 1 to 8 versus weeks 9 to 17.

| Method | Weeks 1-8 (h) | Weeks 9-17 (h) |
| --- | --- | --- |
| No personal pace (baseline) | 0.93 | 1.41 |
| One overall multiplier | 0.79 | 1.15 |
| BeachWell pace model (per type, shrunk) | 0.64 | 0.77 |

## D. Planner (20 synthetic students, whole semester)

| Measure | Default schedule | With BeachWell plan |
| --- | --- | --- |
| Peak week (hours of work) | 41.5 | 30.1 |
| Overload weeks per student | 3.15 | 1.6 |

Rule violations across all plans: **0**. Share of estimated hours placed in study blocks: **99%** (the rest did not fit before its due time).

## E. Event recommendations (24 personas, 18 programs in one week)

| Method | Precision@3 | Hit@1 |
| --- | --- | --- |
| Random (baseline, expected) | 0.134 | 0.134 |
| Most frequent programs (popularity baseline) | 0.083 | 0.167 |
| Keyword overlap (baseline) | 0.472 | 0.625 |
| BeachWell offline (hashed embeddings + rules) | 0.5 | 0.792 |

## F. Safety screen (30 help-needed and 30 everyday-stress messages)

The rules were revised after a first run on this set (crisis recall rose from 0.71 to 1.0), so these numbers are optimistic. Measure again on a fresh, team-written set before quoting them.

| Method | Crisis recall | False-alarm rate | Missed |
| --- | --- | --- | --- |
| Rules only | 1 | 0 | none |
