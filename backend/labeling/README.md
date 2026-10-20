# Labeling guide (about 2 hours each)

Vy and Deborah each fill in **their own** sheets. Do not look at the other person's answers until both are done. The course asks us to show how well two people agree, and that only works if the labels are independent.

## 1. Time estimates (about 1 hour)

Open your file: `effort_labels_vy.csv` or `effort_labels_deborah.csv` (Excel or Google Sheets both work; save as CSV).

For each of the 60 assignments, fill in two columns:

| Column | What to write |
| --- | --- |
| `type` | One word from: exam, quiz, project, presentation, essay, lab, homework, discussion, reading, admin |
| `hours` | How many hours a typical CSULB student spends on it, start to finish. For exams, count study time. Decimals are fine (1.5). |

Use your own experience. There is no "right" answer; we only need your honest estimate.

## 2. Best events for sample students (about 1 hour)

Open `persona_labels_vy.csv` or `persona_labels_deborah.csv`. Each row describes what helps one student recharge.

Pick up to **3 events** that would help that student most, and write their `series_id` in `best_event_1`, `best_event_2` and `best_event_3` (best first). The list of events and their ids is in `event_choices.csv`. At least one pick per row is required.

## 3. Combine and score

When both of you are done, run this from the `backend` folder:

```bash
python scripts/merge_labels.py
python eval/evaluate.py
```

The first command checks that every cell is filled, measures how much you agree, writes the final test labels to `eval/data/`, and saves `labeling/agreement_report.md`. The second re-runs every test with your labels. Quote the numbers from both files in the Phase 2 and final reports.

Until you finish, the project uses draft labels written for the prototype (kept in `eval/data/draft/`).

## 4. Fresh safety messages (about 1 hour, together)

Our safety rules were adjusted using `eval/data/safety_messages.csv`, so testing on that same set is too easy. Write a **new** set in `safety_messages_team.csv`: 30 rows with `label` = `ok` (everyday stress, jokes, "this exam is killing me") and 30 rows with `label` = `crisis` (messages where someone should be shown help). Write them yourselves; do not copy real posts from the internet. `eval/evaluate.py` scores this set separately as the honest, unseen test.
