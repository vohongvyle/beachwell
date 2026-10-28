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

## 4. Safety messages

Our safety rules were first written against `eval/data/safety_messages.csv`, so testing on that set is too easy.

* **Deborah's set (done):** `safety_messages_team.csv`, 15 `ok` and 15 `crisis` rows. On its first, unseen run the Phase 1 rules caught only 6 of the 15 help-needed messages. Its misses were turned into general patterns in `agents/safety.py`, so this set is now a development set.
* **Vy's set (to do, about 30 minutes):** write 15 `ok` rows (everyday stress, jokes, "this exam is killing me") and 15 `crisis` rows (messages where someone should be shown help) in `safety_messages_unseen.csv`. Do not look at `agents/safety.py` or Deborah's set first, and never change the rules after seeing this set's results. `eval/evaluate.py` scores it as the honest, unseen test.

Write the messages yourself; do not copy real posts from the internet.
