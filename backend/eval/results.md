# BeachWell evaluation results

Mode: **offline** (no API key; rules and hashed embeddings). Re-run with `python eval/evaluate.py`.

> Effort and event labels in `eval/data/` come from the team's labeling sheets (see `labeling/agreement_report.md`; so far only Deborah's sheets are filled in, so agreement is not measured yet). Anything learned from labels is tested leave-one-out. Crunch detection, pace learning and the planner use synthetic semesters.

## A. Effort estimation (60 labeled Canvas items)

| Method | Mean abs. error (h) | Median abs. error (h) | Type accuracy | Major-deadline accuracy |
| --- | --- | --- | --- | --- |
| Constant 3 h per deadline (baseline) | 2.98 | 2.0 | 0.133 | 0.567 |
| Type keyword only (baseline) | 2.99 | 2.0 | 0.733 | 0.833 |
| BeachWell rules, Phase 1 (title + description cues) | 2.63 | 2.0 | 0.733 | 0.883 |
| BeachWell rules + calibration from team labels (leave-one-out) | 1.92 | 1.25 | 0.733 | 0.883 |

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
| No personal pace (baseline) | 0.78 | 1.28 |
| One overall multiplier | 0.66 | 1.02 |
| BeachWell pace model (per type, shrunk) | 0.54 | 0.68 |

## D. Planner (20 synthetic students, whole semester)

| Measure | Default schedule | With BeachWell plan |
| --- | --- | --- |
| Peak week (hours of work) | 36.0 | 27.4 |
| Overload weeks per student | 2.6 | 0.95 |

Rule violations across all plans: **0**. Share of estimated hours placed in study blocks: **100%** (the rest did not fit before its due time).

## E. Event recommendations (24 labeled sample students, all 20 catalog programs)

Found@3 = good picks in the top 3 out of the most that were possible (a student with one good option counts as 1/1). MRR = 1 / position of the first good pick. Learned profiles are tested leave-one-out.

| Method | Precision@3 | Found@3 | Hit@1 | MRR |
| --- | --- | --- | --- | --- |
| Random order (baseline, average of 200 shuffles) | 0.12 | 0.149 | 0.118 | 0.3 |
| Most frequent programs (popularity baseline) | 0.069 | 0.076 | 0.125 | 0.268 |
| Keyword overlap (baseline) | 0.389 | 0.514 | 0.583 | 0.725 |
| BeachWell v1 (Phase 1 scoring) | 0.444 | 0.611 | 0.708 | 0.824 |
| BeachWell v2 without learned profiles | 0.5 | 0.681 | 0.875 | 0.927 |
| BeachWell v2 with learned profiles (leave-one-out) | 0.542 | 0.736 | 0.875 | 0.927 |

## F. Safety screen

The first row is the prototype set (30 help-needed, 30 everyday-stress messages) that the rules were written against, so it is optimistic. Deborah's team-written set was unseen the first time: the Phase 1 rules caught only some of its help-needed messages. Those misses were then turned into general patterns, so that set is now a development set. The honest test is Vy's set in `labeling/safety_messages_unseen.csv`, written without looking at the rules; it is scored here once it exists.

| Method | Crisis recall | False-alarm rate | Missed |
| --- | --- | --- | --- |
| Rules only, prototype set | 1 | 0 | none |
| Phase 1 rules, Deborah's set (first, unseen run) | 0.4 | 0.067 | There is no more hope in my life after the professor posted my grade; I am going to end everything after the semester ends; I don't need to exist in this world any more; I don't see any way out of this disastrous semester except to die; I don't care anything anymore; I don't see any hope in my life aftertaking the final exam; I won't let the professor live if he gives me F on my project; You might not see me again tomorrow; There's nothing in my life worth staying alive for |
| Updated rules, Deborah's set (used to fix the rules) | 1 | 0.067 | none |
