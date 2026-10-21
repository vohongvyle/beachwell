# BeachWell

**A weekly workload score for CSULB students.** We're building BeachWell to help students see when their semester may get busy and plan ahead. It uses Canvas deadlines and short daily check-ins to estimate a weekly Workload Score from 0 to 100, labeled Light, Moderate, Heavy, or Overload. It can also make a study plan, suggest small habits for heavier weeks, and recommend campus events that fit a student's free time. The Campus Stress Radar gives ASI, CAPS, and instructors an anonymous view of when larger student groups may be heading into an overload week.

CECS 558 term project, Fall 2026. Team: Vo Hong Vy Le and Deborah Shaw.

## Project timeline

### By Fri Oct 23: prepare the data

- [ ] **Update campus event dates:** Replace the placeholder dates and times in `backend/data/events_catalog.csv` with current ASI, CAPS, and Recreation program information. Add a few events, then run `python scripts/seed.py --reset`.
- [ ] **Label the test data independently:** Vy and Deborah should each complete their own sheets in `backend/labeling/` without viewing the other's labels. Each sheet includes 60 hour estimates and 24 event choices and should take about two hours. See `backend/labeling/README.md`.
- [ ] **Create a fresh safety set:** Together, write 30 everyday-stress and 30 help-needed messages in `backend/labeling/safety_messages_team.csv`. The existing examples were used to tune the rules, so they would make the results look too good.
- [ ] **Compare our labels:** Run `python scripts/merge_labels.py` to calculate Cohen's kappa and create `labeling/agreement_report.md`.

### By Fri Oct 30: evaluate with Gemini

- [ ] Get a Gemini API key from Google AI Studio and add it to `backend/.env`. Keep the key out of GitHub.
- [ ] Run `python eval/evaluate.py` so the Gemini results appear alongside the offline and baseline results.
- [ ] Review `GET /api/llm-log` and record Gemini's latency, failures, and the hour estimates with the largest errors.

### By Fri Nov 13: finish the app on GitHub

- [ ] **Commit our work:** for the backend, AI agents, and evaluation. the web app, event list, and documentation. Before pushing, check that the repository contains no API keys or personal data.
- [ ] **Test a Canvas feed:** Each of us should import our own `.ics` file locally and check that the reader works. Don't upload the feed anywhere.
- [ ] **Polish the web app:** Check the phone layout and wording on each screen. The page background is currently white; `#F6F8F8` is another option.

### By Fri Nov 20: Phase 2

- [ ] Write a two-page progress report covering what we built, the evaluation with our labels and Gemini, and changes since Phase 1.
- [ ] Finish the GitHub documentation: this README, `docs/AI_WORKFLOW.md` with prompts, inputs, outputs, and limitations, and instructions for reproducing the results.

### By Fri Dec 4: test with classmates and review errors

- [ ] **Run a usability test:** Ask about 8–10 classmates to follow `usability/test_script.md`. Record their answers in `usability/sus_responses.csv`, then run `python scripts/score_sus.py`.
- [ ] **Review errors:** Find examples with inaccurate hour estimates or poor event recommendations and describe them in the final report.

Both of us should be ready to explain the whole system, since either teammate may be asked about it.

> BeachWell helps with planning and recommendations. It does not diagnose conditions or give health advice. If a check-in indicates a crisis, the app shows a fixed response directing the student to CSULB CAPS.

## What BeachWell does

| Screen | What the student sees | How it works |
| --- | --- | --- |
| Workload | This week's score (0–100) and level, reasons for the score, and a seven-week bar chart | Deadline Agent estimates effort; Workload Agent calculates the score |
| What-if slider | Changes scores after moving an assignment earlier or choosing “follow my plan” | Workload Agent recalculates with the updated inputs |
| Plan | Study blocks of 90 minutes or less with breaks, workload levels before and after planning, habit tips, and `.ics` export | Planner Agent schedules work and checks the rules |
| Recharge | Two or three de-stress events for each heavy week, matched to free time and interests | Event Recommender uses embeddings, rules, and Gemini re-ranking |
| Check-in | A quick sleep and stress check-in; the note is screened for safety and then discarded | Safety Agent |
| My pace | A personal estimate such as “You take 30% longer than estimated on essays,” based on logged hours | Pace model learns from actual hours |
| Campus Radar | A heatmap by college and week, overload alerts, and deadline collisions with a what-if option | Radar Agent uses anonymous groups of 10 or more students |

## Evaluation

These offline-mode results are from `backend/eval/results.md`.

| Component | Baseline | BeachWell |
| --- | --- | --- |
| Effort estimates, mean absolute error (60 labeled items) | 2.58 h (type keyword only) | **1.75 h** |
| Finding crunch weeks, F1 (40 synthetic semesters) | 0.67 (deadline count) | **1.00** |
| Pace learning, error in weeks 9–17 (40 simulated students) | 1.41 h (no pace model) | **0.77 h** |
| Planner, average peak week (20 synthetic students) | 41.5 h | **30.1 h**, 0 rule violations |
| Planner, overload weeks per student | 3.15 | **1.6** |
| Event picks, Precision@3 (24 personas) | 0.47 (keyword overlap) | **0.50**, Hit@1 0.79 vs. 0.63 |
| Safety screen, crisis recall (28 messages) | – | 1.00 with 0 false alarms* |

These results are preliminary. The labels are placeholders, and three of the six evaluations use synthetic data; see the notes in `eval/results.md`. *We adjusted the safety rules after an initial run on this set, so we'll need to evaluate them again with fresh messages. Run `python eval/evaluate.py` with a Gemini key to add Gemini results.

## Screenshots

| | |
| --- | --- |
| ![What-if slider](docs/screenshots/3-what-if.png) | ![Study plan](docs/screenshots/4-plan.png) |
| ![Recharge picks](docs/screenshots/5-recharge.png) | ![Campus Radar](docs/screenshots/7-radar.png) |

## Main API endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/users` | Create a student |
| POST | `/api/users/{id}/calendar` | Import a Canvas feed (`{url}` or `{ics}`) |
| PUT | `/api/users/{id}/classes` | Set weekly class times |
| GET, POST | `/api/users/{id}/forecast` | Get workload scores; POST supports what-if inputs (`extra_lead`, `use_plan`) |
| GET | `/api/users/{id}/plan`, `/plan.ics` | Get the study plan or download it as a calendar file |
| GET | `/api/users/{id}/events` | Get de-stress event picks for heavy weeks |
| POST | `/api/users/{id}/checkins` | Submit a check-in with safety screening |
| GET | `/api/users/{id}/pace` | Get the personal pace model |
| PATCH | `/api/users/{id}/tasks/{task_id}` | Log actual hours, correct an estimate, or mark a task done |
| GET | `/api/radar` | View the Campus Stress Radar |
| GET | `/api/llm-log` | View recent Gemini calls (name, latency, success) |

## Project data

BeachWell does not have real student data. The files below are generated by our code, copied from public CSULB pages, or written by our team.

| File | What it contains | Source or notes |
| --- | --- | --- |
| `backend/data/events_catalog.csv` | 20 recurring campus programs (title, place, days, times, tags) | Public ASI, CAPS, and Recreation pages; clubs marked “sample” are invented. Update as needed, then run `python scripts/seed.py --reset`. |
| `backend/data/sample_canvas_feed.ics` | Canvas-style calendar feed for five courses (89 deadlines) | Generated; upload on the welcome screen to test importing. |
| `backend/data/sample_canvas_feed_business.ics` | Another feed with four business and GE courses | Generated. |
| `backend/eval/data/practice_semesters.json` and `_deadlines.csv` | 40 practice semesters, each with one known crunch week and one decoy week | Generated by `scripts/make_practice_semesters.py`. |
| `backend/eval/data/effort_labels.csv` | 60 assignment titles with types and hour estimates | Draft labels; replace with the team's averaged labels after `merge_labels.py`. |
| `backend/eval/data/event_personas.json` | 24 sample students and their best-fitting events | Draft labels, to be updated by the team. |
| `backend/eval/data/safety_messages.csv` | 30 everyday-stress and 30 help-needed messages | Written for the prototype. |
| `backend/labeling/` | Blank sheets for Vy and Deborah, event list, and fresh safety set | Completed by our team; see `labeling/README.md` (about two hours per person). |
| `usability/` | Test script, SUS survey, and response sheet for 8–10 classmates | Completed by our team; see `usability/test_script.md`. |

### Data workflow

1. Vy and Deborah each complete their own sheets in `backend/labeling/` without looking at the other's answers.
2. Together, write 60 new safety messages in `backend/labeling/safety_messages_team.csv`.
3. Run `python scripts/merge_labels.py`, then `python eval/evaluate.py`.
4. Run the classmate test, enter responses in `usability/sus_responses.csv`, and run `python scripts/score_sus.py`.
5. Include `labeling/agreement_report.md`, `eval/results.md`, and `usability/sus_results.md` in the project reports.

## Data, privacy, and responsible AI

- All prototype data is **sample or synthetic**. Event organizers and venues are real CSULB programs, but dates and times are placeholders.
- Canvas feed links are used once and not stored. Check-in notes are screened for safety and then discarded; only the two numerical answers are kept.
- A student can request deletion of their data with `DELETE /api/users/{id}`.
- The Campus Radar includes only students who opt in and does not show groups smaller than 10.
- People wrote the fixed crisis response; the language model does not generate it.
- Workload scores are estimates and are presented as such. Students can correct effort estimates.

## Known limitations

- Gemini support is implemented and tested with mocked responses, but the published numbers are from offline mode. Run `python eval/evaluate.py` with an API key to evaluate the Gemini versions.
- Evaluation labels are placeholders and should be completed independently by both teammates.
- The semester calendar, including its start date and Thanksgiving week, is a placeholder. Set it in `.env`.
- SQLite works for this prototype. A campus deployment would need PostgreSQL and CSULB SSO sign-in.
- The “expected events” projection assumes recurring programs stay in the same week of the semester.

License: MIT.

