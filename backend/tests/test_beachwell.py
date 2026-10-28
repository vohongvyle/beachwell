"""Unit and integration tests. Run from backend/:  python -m unittest -v   (or: pytest)

They run fully offline (no Gemini key needed) against a temporary database.
"""
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

_tmp = tempfile.mkdtemp()
os.environ["DB_PATH"] = str(Path(_tmp) / "test.db")
os.environ["BEACHWELL_OFFLINE"] = "1"
os.environ["DEMO_TODAY"] = "2026-10-12"
os.environ["SEMESTER_START"] = "2026-08-24"

from beachwell import ical, llm, seed, semester, service  # noqa: E402
from beachwell.agents import deadline, events, forecast, pace, planner, radar, safety  # noqa: E402

TODAY = date(2026, 10, 12)


def task(i, title, due, hours, kind="homework", major=False, done=False):
    return {"id": i, "title": title, "course": "TEST 101", "due": due.isoformat(), "hours": hours,
            "type": kind, "major": major, "done": done}


def at(d: date, h: float = 23.98):
    return ical.local_dt(d, h)


class TestICal(unittest.TestCase):
    def test_canvas_summary_course_and_times(self):
        text = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:a1\r\nDTSTART:20261017T065900Z\r\nDTEND:20261017T065900Z\r\n"
                "SUMMARY:Phase 1 Report [CECS 458 Sec 01 Fall 2026]\r\nDESCRIPTION:Max 4 pages\\, team\r\n"
                "  report\r\nEND:VEVENT\r\nBEGIN:VEVENT\r\nUID:a2\r\nDTSTART;VALUE=DATE:20261020\r\nSUMMARY:Quiz 3 [MATH 380]\r\n"
                "END:VEVENT\r\nEND:VCALENDAR\r\n")
        items = ical.parse_ics(text)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].course, "CECS 458")
        self.assertEqual(items[0].title, "Phase 1 Report")
        self.assertEqual(items[0].due.strftime("%Y-%m-%d %H:%M"), "2026-10-16 23:59")  # UTC -> Pacific
        self.assertEqual(items[0].description, "Max 4 pages, team report")  # unescaped and unfolded
        self.assertTrue(items[1].all_day)

    def test_write_then_read_roundtrip(self):
        d = date(2026, 10, 20)
        text = ical.write_ics([{"uid": "x", "title": "Study: Essay, part 1", "start": ical.local_dt(d, 9),
                                "end": ical.local_dt(d, 10.5)}])
        self.assertIn("BEGIN:VCALENDAR", text)
        back = ical.parse_ics(text)
        self.assertEqual(back[0].title, "Study: Essay, part 1")


class TestDeadlineRules(unittest.TestCase):
    def test_types_and_major(self):
        cases = {"Midterm Exam": ("exam", True), "Quiz 4": ("quiz", False), "Reading Response 3": ("reading", False),
                 "Lab Report 2": ("lab", False), "Final Project Report": ("project", True),
                 "Discussion Post 5": ("discussion", False), "Group Presentation": ("presentation", True)}
        for title, (kind, major) in cases.items():
            e = deadline.estimate_rules(title)
            self.assertEqual((e.type, e.major), (kind, major), title)

    def test_pages_and_points_raise_hours(self):
        short = deadline.estimate_rules("Essay 1").hours
        long = deadline.estimate_rules("Essay 2", "10-12 pages").hours
        self.assertGreater(long, short)
        self.assertGreater(deadline.estimate_rules("Project", "200 points").hours, deadline.estimate_rules("Project").hours)

    def test_calibration_from_labels(self):
        base = deadline.estimate_rules("Quiz 4", calibrate=False).hours
        self.assertEqual(deadline.estimate_rules("Quiz 4", calibration={"quiz": 2.0}).hours, base * 2)
        self.assertEqual(deadline.estimate_rules("Quiz 4", calibration={}).hours, base)
        rows = [{"title": f"Quiz {i}", "description": "", "hours": base * 3} for i in range(2)] + \
               [{"title": f"Homework {i}", "description": "", "hours": deadline.estimate_rules("Homework", calibrate=False).hours}
                for i in range(6)]
        mult = deadline.learn_calibration(rows, shrink=2)
        self.assertGreater(mult["quiz"], 1.5)      # learned that quizzes take longer...
        self.assertLess(mult["quiz"], 3.0)         # ...but shrunk, since only 2 quizzes were labeled
        self.assertAlmostEqual(mult["homework"], 1.0, places=2)

    def test_batch_offline_uses_rules(self):
        out = deadline.estimate_batch([{"title": "Quiz 1", "course": "X"}])
        self.assertEqual(out[0].source, "rules")


class TestPace(unittest.TestCase):
    def test_no_history_is_neutral(self):
        self.assertAlmostEqual(pace.fit([]).multiplier("essay"), 1.0)

    def test_learns_and_shrinks(self):
        m = pace.fit([("essay", 4, 6)] * 6)  # always 1.5x
        self.assertGreater(m.multiplier("essay"), 1.25)
        self.assertLess(m.multiplier("essay"), 1.5)  # shrinkage keeps it below the raw ratio
        one = pace.fit([("essay", 4, 6)])
        self.assertLess(one.multiplier("essay"), m.multiplier("essay"))  # less data, less correction

    def test_student_number_wins(self):
        m = pace.fit([("essay", 4, 8)] * 5)
        self.assertEqual(pace.effective_hours({"user_hours": 3, "base_hours": 5, "type": "essay"}, m), 3.0)


class TestForecast(unittest.TestCase):
    def setUp(self):
        self.w = semester.week_of(TODAY)
        self.next_start = semester.week_start(self.w + 2)

    def test_crunch_is_heavy_and_quiet_week_is_light(self):
        d = self.next_start
        # a normal background week of homework (about 12 h), plus a crunch in week w+2
        tasks = [task(100 + i, f"HW {i}", at(semester.week_start(self.w + i // 3) + timedelta(days=i % 3)), 4)
                 for i in range(9)]
        tasks += [task(1, "Final Project Report", at(d + timedelta(days=1)), 14, "project", True),
                 task(2, "Midterm Exam", at(d + timedelta(days=2), 10), 8, "exam", True),
                 task(3, "Essay", at(d + timedelta(days=3)), 9, "essay", True)]
        weeks = {w.week: w for w in forecast.forecast(tasks, TODAY, 25, None, 6)}
        self.assertIn(weeks[self.w + 2].level, ("Heavy", "Overload"))
        self.assertEqual(weeks[self.w + 5].level, "Light")
        self.assertTrue(any("major deadlines" in r for r in weeks[self.w + 2].reasons))

    def test_many_small_items_are_not_an_overload(self):
        d = self.next_start
        tasks = [task(i, f"Quiz {i}", at(d + timedelta(days=i % 5)), 1.5, "quiz") for i in range(6)]
        weeks = {w.week: w for w in forecast.forecast(tasks, TODAY, 25, None, 4)}
        self.assertIn(weeks[self.w + 2].level, ("Light", "Moderate"))

    def test_starting_earlier_moves_hours_earlier(self):
        d = self.next_start + timedelta(days=4)
        tasks = [task(1, "Project", at(d), 20, "project", True)]
        base = {w.week: w.hours for w in forecast.forecast(tasks, TODAY, 25, None, 4)}
        early = {w.week: w.hours for w in forecast.forecast(tasks, TODAY, 25, None, 4, extra_lead={1: 7})}
        self.assertLess(early[self.w + 2], base[self.w + 2])
        self.assertAlmostEqual(sum(early.values()), sum(base.values()), delta=0.3)  # weekly totals are rounded

    def test_sleep_debt_raises_current_week(self):
        tasks = [task(1, "Project", at(TODAY + timedelta(days=3)), 12, "project", True)]
        checkins = [{"day": (TODAY - timedelta(days=i)).isoformat(), "sleep_hours": 8 if i > 3 else 5, "stress": 4}
                    for i in range(8)]
        plain = forecast.forecast(tasks, TODAY, 25, None, 1)[0].score
        tired = forecast.forecast(tasks, TODAY, 25, checkins, 1)[0].score
        self.assertNotEqual(plain, tired)


class TestPlanner(unittest.TestCase):
    def test_rules_hold_on_a_full_semester(self):
        tasks, k = [], 0
        for course in ["CECS 458", "MATH 380", "ENGL 317", "BIOL 211", "FIN 300"]:
            for it in seed.course_items(course):
                e = deadline.estimate_rules(it.title, it.description)
                k += 1
                tasks.append({"id": k, "title": it.title, "course": course, "due": seed.item_due(it).isoformat(),
                              "hours": e.hours, "type": e.type, "major": e.major, "done": False})
        classes = [{"course": c, "weekday": d, "start_hour": s, "end_hour": e} for c, d, s, e in seed.DEMO_CLASSES]
        out = planner.plan(tasks, classes, TODAY, daily_cap=5, weekly_capacity=25)
        self.assertEqual(planner.check_constraints(out, tasks, classes, 5), [])
        self.assertGreater(len(out["blocks"]), 50)
        for b in out["blocks"]:  # lunch stays free
            self.assertFalse(b["start_hour"] < 13 and b["end_hour"] > 12, b)

    def test_habits_only_for_heavy_weeks(self):
        self.assertEqual(planner.habits_for({"level": "Light"}, None, []), [])
        tips = planner.habits_for({"level": "Overload"}, {"sleep_deficit": 1.5, "stress_recent": 4}, [])
        self.assertTrue(1 <= len(tips) <= 2)
        self.assertEqual(tips[0]["id"], "sleep-window")


class TestSafety(unittest.TestCase):
    def test_flags_crisis_language(self):
        for text in ["I want to die", "thinking about killing myself", "I don't want to be alive anymore",
                     "I keep wanting to hurt myself"]:
            self.assertEqual(safety.check(text)["level"], "crisis", text)

    def test_ignores_everyday_exaggeration(self):
        for text in ["this exam is killing me", "I'm dead tired", "midterms are going to be the death of me", ""]:
            self.assertEqual(safety.check(text)["level"], "ok", text)

    def test_flags_hopelessness_finality_and_threats(self):
        # phrasings added after the team-written set; these exact sentences are not in that set
        for text in ["I've lost all hope", "you won't ever see me again", "I'm going to end everything tonight",
                     "I don't deserve to be alive", "I won't let my roommate live", "nothing left worth living for",
                     "I don't care about anything anymore"]:
            self.assertTrue(safety.rules_flag(text), text)
        for text in ["No hope for this group project", "I don't care about this class anymore",
                     "I'll see you again tomorrow", "I'm hopeless at calculus", "I won't let the professor down"]:
            self.assertFalse(safety.rules_flag(text), text)

    def test_response_is_fixed_text(self):
        r = safety.check("I want to end my life")
        self.assertIn("988", " ".join(c["action"] for c in r["contacts"]))


class TestEvents(unittest.TestCase):
    def _ev(self, i, tags, start, hours=1.0, series=""):
        return {"id": str(i), "title": f"Event {i}", "organizer": "Org", "description": "A campus event.", "tags": tags,
                "start": start.isoformat(), "end": (start + timedelta(hours=hours)).isoformat(), "location": "",
                "series": series, "source_url": "", "is_sample": 1}

    def test_crowd_averse_students_skip_big_crowds(self):
        t = at(TODAY + timedelta(days=2), 12)
        evs = [self._ev(1, "music,large-crowd,destress", t), self._ev(2, "yoga,calm,destress,small-group", t)]
        ranked = events.score_events("yoga please, I hate crowds", evs)
        self.assertEqual([e["id"] for _, e in ranked], ["2"])

    def test_learned_profiles_and_stemming(self):
        t = at(TODAY + timedelta(days=2), 12)
        rest = {**self._ev(1, "quiet,rest", t, series="rest"), "title": "Quiet room", "description": "Recliners and dim lights."}
        yoga = {**self._ev(2, "yoga,fitness", t, series="yoga"), "title": "Yoga", "description": "Stretch and breathe."}
        prof = events.build_profiles([{"interests": "I really need sleep", "gold": ["rest"]},
                                      {"interests": "stretching and moving", "gold": ["yoga"]}])
        ranked = events.score_events("so tired, I need sleep", [yoga, rest], profiles=prof)
        self.assertEqual(ranked[0][1]["series"], "rest")
        self.assertIn("paint", llm.tokens("painting"))
        self.assertIn("hike", llm.tokens("hiking"))

    def test_time_fit(self):
        mon = semester.week_start(semester.week_of(TODAY) + 1)
        ev = self._ev(1, "yoga", at(mon, 14))
        self.assertFalse(events.fits_free_time(ev, [{"weekday": 0, "start_hour": 13.5, "end_hour": 15}], []))
        self.assertTrue(events.fits_free_time(ev, [{"weekday": 1, "start_hour": 13.5, "end_hour": 15}], []))

    def test_recurring_events_are_projected_as_expected(self):
        past = at(date(2025, 12, 15), 10)  # a past-term finals-week event
        out = events.project_expected([self._ev(1, "food", past, 2, series="finals")], TODAY)
        self.assertTrue(out and out[0]["expected"])
        self.assertGreaterEqual(datetime.fromisoformat(out[0]["start"]).date(), TODAY)


class TestRadarPrivacy(unittest.TestCase):
    def test_small_groups_are_suppressed_and_no_ids_leak(self):
        d = semester.week_start(semester.week_of(TODAY) + 1)
        users = [{"id": i, "college": "Big" if i < 12 else "Tiny", "weekly_capacity": 20, "radar_opt_in": 1}
                 for i in range(15)]
        tasks = {u["id"]: [task(100 + u["id"], "Final Project", at(d), 25, "project", True)] for u in users}
        out = radar.campus_radar(users, tasks, TODAY, min_group=10)
        self.assertEqual([r["group"] for r in out["heatmap"]], ["Big"])
        self.assertEqual(out["suppressed_groups"], 1)
        self.assertNotIn("user_id", str(out))


class TestServiceFlow(unittest.TestCase):
    """End to end through the service layer, the same calls the API makes."""

    def test_new_student_flow(self):
        u = service.create_user("Test", "I like yoga and quiet places", "Engineering", 25)
        res = service.import_ics(u["id"], seed.course_ics(["CECS 458", "MATH 380"]))
        self.assertGreater(res["added"], 20)
        again = service.import_ics(u["id"], seed.course_ics(["CECS 458", "MATH 380"]))
        self.assertEqual(again["added"], 0)  # re-import does not duplicate
        service.set_classes(u["id"], [{"course": "CECS 458", "weekday": 0, "start_hour": 14, "end_hour": 15.25}])
        f = service.user_forecast(u["id"])
        self.assertEqual(len(f["weeks"]), 7)
        p = service.user_plan(u["id"])
        self.assertEqual(p["violations"], [])
        self.assertIn("BEGIN:VEVENT", service.plan_ics(u["id"]))
        crisis = service.add_checkin(u["id"], 5, 5, "honestly I want to die")
        self.assertEqual(crisis["safety"]["level"], "crisis")
        t = service.list_tasks(u["id"])[0]
        updated = service.update_task(t["id"], u["id"], actual_hours=6, done=True)
        self.assertTrue(updated["done"])
        service.delete_user(u["id"])
        with self.assertRaises(service.NotFound):
            service.get_user(u["id"])

    def test_feed_url_must_be_canvas_https(self):
        for bad in ["http://csulb.instructure.com/feed.ics", "https://example.com/feed.ics", "file:///etc/passwd"]:
            with self.assertRaises(service.BadRequest):
                service._check_feed_url(bad)


class TestDataFiles(unittest.TestCase):
    """The data files the report describes exist and load."""

    def test_event_catalog_csv(self):
        rows = seed.load_catalog()
        self.assertEqual(len(rows), 20)
        self.assertEqual(len({r[0] for r in rows}), 20)  # unique ids
        for r in rows:
            self.assertLess(r[7], r[8], r[0])  # start before end

    def test_eval_sets_sizes(self):
        import csv, json
        base = Path(__file__).resolve().parent.parent / "eval" / "data"
        self.assertEqual(len(list(csv.DictReader(open(base / "effort_labels.csv")))), 60)
        self.assertEqual(len(json.load(open(base / "event_personas.json"))), 24)
        labels = [r["label"] for r in csv.DictReader(open(base / "safety_messages.csv"))]
        self.assertEqual((labels.count("crisis"), labels.count("ok")), (30, 30))
        sems = json.load(open(base / "practice_semesters.json"))["semesters"]
        self.assertEqual(len(sems), 40)

    def test_persona_gold_ids_exist(self):
        import json
        base = Path(__file__).resolve().parent.parent
        ids = {r[0] for r in seed.load_catalog()}
        for p in json.load(open(base / "eval" / "data" / "event_personas.json")):
            self.assertTrue(set(p["gold"]) <= ids, p)

    def test_sample_feed_parses(self):
        base = Path(__file__).resolve().parent.parent / "data"
        self.assertGreater(len(ical.parse_ics(open(base / "sample_canvas_feed.ics").read())), 50)


class TestScoringScripts(unittest.TestCase):
    def test_sus_score(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("score_sus", Path(__file__).resolve().parent.parent / "scripts" / "score_sus.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(mod.sus_score([5, 1] * 5), 100.0)
        self.assertEqual(mod.sus_score([3] * 10), 50.0)
        self.assertEqual(mod.sus_score([1, 5] * 5), 0.0)

    def test_cohen_kappa(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("merge_labels", Path(__file__).resolve().parent.parent / "scripts" / "merge_labels.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertAlmostEqual(mod.cohen_kappa(["a", "b", "a", "b"], ["a", "b", "a", "b"]), 1.0)
        self.assertAlmostEqual(mod.cohen_kappa(["a", "a", "b", "b"], ["a", "b", "a", "b"]), 0.0)


class TestGeminiClient(unittest.TestCase):
    """The Gemini code path, with the HTTP call mocked (no key or network needed)."""

    def setUp(self):
        from beachwell import llm
        self.llm = llm
        os.environ["GEMINI_API_KEY"] = "test-key"
        os.environ["BEACHWELL_OFFLINE"] = "0"

    def tearDown(self):
        os.environ.pop("GEMINI_API_KEY", None)
        os.environ["BEACHWELL_OFFLINE"] = "1"

    def _fake(self, payload):
        from unittest import mock
        resp = mock.Mock()
        resp.json.return_value = payload
        resp.raise_for_status.return_value = None
        return mock.patch.object(self.llm.requests, "post", return_value=resp)

    def test_deadline_estimates_parse_gemini_json(self):
        answer = '```json\n[{"type": "project", "hours": 15, "major": true, "reason": "long report"}]\n```'
        with self._fake({"candidates": [{"content": {"parts": [{"text": answer}]}}]}) as post:
            out = deadline.estimate_batch([{"title": "Final Report", "course": "CECS 458"}])
        self.assertEqual((out[0].type, out[0].hours, out[0].source), ("project", 15.0, "gemini"))
        url = post.call_args.args[0]
        self.assertIn(":generateContent", url)
        self.assertEqual(post.call_args.kwargs["headers"]["x-goog-api-key"], "test-key")
        self.assertEqual(post.call_args.kwargs["json"]["generationConfig"]["responseMimeType"], "application/json")

    def test_bad_gemini_answer_falls_back_to_rules(self):
        with self._fake({"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}):
            out = deadline.estimate_batch([{"title": "Quiz 2", "course": "X"}])
        self.assertEqual(out[0].source, "rules")

    def test_embeddings_are_normalised(self):
        with self._fake({"embeddings": [{"values": [3.0, 4.0] + [0.0] * 766}]}) as post:
            vec = self.llm.embed(["unique text for embedding test"])
        self.assertAlmostEqual(float((vec[0] ** 2).sum()), 1.0, places=5)
        self.assertEqual(post.call_args.kwargs["json"]["requests"][0]["outputDimensionality"], 768)


if __name__ == "__main__":
    unittest.main()
