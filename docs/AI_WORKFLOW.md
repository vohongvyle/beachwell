# AI workflow: prompts, inputs, outputs and limitations

The CECS 458/558 project rules ask teams that use an external LLM API to document the prompts and API workflow, input-output behavior, limitations, and the team's own technical contribution. This page does that for BeachWell.

## Where Gemini is used, and where it is not

BeachWell uses Gemini in four narrow places. The parts that decide numbers a student acts on (the workload score, the study schedule, the privacy rules, the crisis response) are deterministic code written by the team, so they can be explained, tested and guaranteed.

| Step | Gemini's job | What the team's code does around it |
| --- | --- | --- |
| Deadline estimates | Read assignment titles and descriptions, return type and hours | Batches 40 items per call; validates types and clamps hours to 0.25–40; falls back to rules per batch; student can override any estimate |
| Event matching | Embed interests and event text; re-rank the top 8 and write reasons | Time-fit filter, crowd preference rule, diversity across weeks, offline hashed embeddings, template reasons |
| Habit tips | Reword chosen tips for the student's interests | Chooses which tips apply (rules on the workload score and check-ins); keeps ids; rejects malformed output |
| Safety screen | Second opinion on free text ("crisis" or "ok") | Rules run first; either layer flagging routes to help; response text is fixed |

Not using an LLM: the workload score, the scheduler, the pace model, the Campus Radar and every privacy rule.

## API workflow

All calls go through `backend/beachwell/llm.py`, using the Gemini REST API with the key in the `x-goog-api-key` header (read from the environment, never committed).

* **Text:** `POST https://generativelanguage.googleapis.com/v1beta/models/{LLM_MODEL}:generateContent` with `generationConfig.responseMimeType = "application/json"`, temperature 0.2 (0.0 for safety). Code fences are stripped before parsing.
* **Embeddings:** `POST …/models/{EMBEDDING_MODEL}:batchEmbedContents` with `outputDimensionality = 768`. Vectors are re-normalised (truncated dimensions are not unit length) and cached in memory.
* **Failure handling:** any network error, quota error or malformed JSON returns `None`, and the caller uses its offline path. A request never fails because Gemini did.
* **Logging:** every call records its prompt name, latency and success. See `GET /api/llm-log`.

## Prompts

### 1. Deadline estimates (`agents/deadline.py`, `PROMPT`)

* **Input:** up to 40 lines of JSON, each `{"title", "course", "description"}` (description cut to 300 characters).
* **Prompt summary:** "You estimate student workload… return its type and the realistic number of hours an average undergraduate spends on it (for exams: total preparation hours)." Four few-shot examples (quiz, long final report, discussion post, midterm). Types are listed explicitly.
* **Output:** a JSON list, same order, each `{"type", "hours", "major", "reason"}`.
* **Validation:** list length must match; unknown types fall back to the rule-based type; hours clamped to 0.25–40; "major" recomputed with the team's rule (exams, projects, presentations, essays of 4+ hours).

### 2. Event re-ranking (`agents/events.py`, `RERANK_PROMPT`)

* **Input:** the student's interests, the week's level and reasons, and the 8 best candidates after the time-fit filter (id, title, time, description, tags).
* **Prompt summary:** "Pick the 3 events that would help this student recharge most, respecting stated dislikes. For each, write one friendly sentence (max 22 words)."
* **Output:** `[{"id", "reason"}]`.
* **Validation:** only ids from the candidate list are accepted (Gemini cannot invent an event); reasons cut to 200 characters.

### 3. Habit wording (`agents/planner.py`, `personalise_habits`)

* **Input:** one or two tips already chosen by rules, and the student's interests.
* **Output:** a JSON list of strings, same length and order, otherwise the original tips are kept.

### 4. Safety second opinion (`agents/safety.py`, `PROMPT`)

* **Input:** the free text, cut to 1,000 characters.
* **Prompt summary:** decide whether the message suggests risk of suicide, self-harm or harming others; everyday exaggeration about school is not risk; "when unsure, answer crisis."
* **Output:** `{"label": "crisis" | "ok"}`. Only adds flags; it can never clear a message the rules flagged.

## The team's own technical contribution

* **Workload Agent:** a transparent load index combining work spread over each task's window, major-deadline density within 4 days, deadline pressure, and sleep and stress check-ins, with reasons generated from the largest contributions (`agents/forecast.py`).
* **Personal pace model:** empirical-Bayes shrinkage of log(actual/estimate) per assignment type toward the student's overall ratio (`agents/pace.py`).
* **Planner:** earliest-deadline-first scheduling with least-loaded-day placement and a weekly capacity penalty, protected meal times, and a rule checker used in tests and evaluation (`agents/planner.py`).
* **Event Recommender:** hybrid retrieval (embeddings plus literal-word overlap), free-time fitting for short and drop-in events, crowd preference, diversity across weeks, and projection of recurring past-term events as "expected" (`agents/events.py`).
* **Campus Radar:** k-anonymous aggregation (no group under 10), overload alerts, and deadline-collision detection with a what-if for moving a deadline one week (`agents/radar.py`).
* **Canvas integration:** a dependency-free iCalendar reader and writer, with an allow-list for feed hosts and a private-address check (`ical.py`, `service.py`).
* **Learning from the team's labels:** `scripts/learn_from_labels.py` learns event profiles (relevance feedback from labeled sample students) and a per-type effort calibration (shrunk log-ratio, like the pace model). The evaluation tests both leave-one-out.
* **Evaluation:** six experiments, each against a non-AI baseline (`eval/evaluate.py`).

## Limitations

* Gemini outputs vary between runs and model versions. Pin `LLM_MODEL` and re-run `eval/evaluate.py` after any change.
* Effort estimates reflect an "average undergraduate"; the pace model corrects this only after a student logs hours.
* The offline embedding is a hashed bag of words with a small synonym list. It is a fallback, not a substitute for semantic embeddings.
* The safety screen is a routing aid, not a clinical assessment. It is tuned for recall, so it will sometimes show crisis resources to a student who is fine.
* Evaluation labels so far come from one team member (Deborah); a second set is needed to measure agreement. Learned profiles and calibration reflect the labelers' judgment and should be re-learned as more labels arrive.
