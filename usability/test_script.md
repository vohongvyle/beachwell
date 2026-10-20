# Classmate usability test (10 minutes per person)

Goal: 8–10 classmates try BeachWell with the sample courses and answer a short survey. Nobody connects their own Canvas account and we keep no personal data, only the anonymous survey answers.

## Before the session

1. Start the app on your laptop (see the main README) and open http://localhost:8000.
2. If someone used the laptop before, click **Switch student** so the welcome screen shows.
3. Have the survey ready: a Google Form with the questions below, or a printed copy.

## What to say (consent)

> "Thanks for helping. This is a class project called BeachWell, an app that scores how heavy each week of the semester will be. You'll use made-up sample classes, not your own. It takes about 10 minutes, then a short anonymous survey. We're testing the app, not you, and you can stop at any time. Is that okay?"

Only continue if they say yes. Do not record names, screens or audio.

## Tasks (read one at a time; don't help unless they are stuck for a minute)

1. Click **Open the demo**. "Which week has the highest workload score, and why does the app say so?"
2. "Use the slider to start the CECS 458 Midterm 10 days earlier. What changed?"
3. "Open the study plan. When is your first study session for Essay 2?"
4. "Find one campus event you might actually go to in an overload week."
5. "Do a check-in: you slept 6 hours and feel stressed (4)."

For each task, note in your own sheet: done without help / done with a hint / not done. This counts toward the "task success rate" in the report.

## Survey

### System Usability Scale (SUS)
Answer each from 1 (strongly disagree) to 5 (strongly agree):

1. I think that I would like to use this app frequently.
2. I found the app unnecessarily complex.
3. I thought the app was easy to use.
4. I think that I would need the support of a technical person to be able to use this app.
5. I found the various functions in this app were well integrated.
6. I thought there was too much inconsistency in this app.
7. I would imagine that most people would learn to use this app very quickly.
8. I found the app very cumbersome to use.
9. I felt very confident using the app.
10. I needed to learn a lot of things before I could get going with this app.

### Two extra questions
- Would you follow a study plan like this during midterms? (yes / maybe / no)
- Would you go to one of the suggested events? (yes / maybe / no)

### Optional
- What did you like most?
- What was most confusing?

## After the sessions

Type every answer into `usability/sus_responses.csv` (one row per person, `participant` = P1, P2, …), then run from the `backend` folder:

```bash
python scripts/score_sus.py
```

It prints the average SUS score (0–100; about 68 is average for software) and the share of "yes" answers, and saves `usability/sus_results.md` for the report.
