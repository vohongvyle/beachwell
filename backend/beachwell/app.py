"""HTTP API (Starlette) and the static web app.

Run from backend/:   uvicorn beachwell.app:app --reload --port 8000
Then open http://localhost:8000 for the app, or http://localhost:8000/api for the endpoint list.
"""
from __future__ import annotations

import contextlib
import logging
import threading

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import __version__, db, llm, seed as seed_mod, semester, service
from .agents import safety
from .config import PROJECT_DIR, get_settings

log = logging.getLogger("beachwell")

ROUTES_DOC: list[tuple[str, str, str]] = []


def api(path: str, methods: list[str], doc: str):
    def wrap(fn):
        async def endpoint(request: Request):
            try:
                result = await fn(request)
                return result if isinstance(result, Response) else JSONResponse(result)
            except service.NotFound as exc:
                return JSONResponse({"error": str(exc)}, status_code=404)
            except (service.BadRequest, ValueError, KeyError, TypeError) as exc:
                return JSONResponse({"error": str(exc) or exc.__class__.__name__}, status_code=400)

        ROUTES_DOC.extend((m, path, doc) for m in methods)
        return Route(path, endpoint, methods=methods)

    return wrap


async def body(request: Request) -> dict:
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def uid(request: Request) -> int:
    return int(request.path_params["user_id"])


# ---------------------------------------------------------------- general

@api("/api/health", ["GET"], "Server status, AI mode (gemini/offline) and the current semester week")
async def health(request):
    s = get_settings()
    today = s.today()
    return {"ok": True, "version": __version__, "mode": llm.mode(), "llm_model": s.llm_model,
            "embedding_model": s.embedding_model, "today": today.isoformat(),
            "week": semester.week_of(today), "week_label": semester.week_label(max(1, semester.week_of(today)))}


@api("/api/demo", ["GET"], "The demo student's id (seeded by scripts/seed.py)")
async def demo(request):
    with db.session() as c:
        row = db.one(c.execute("SELECT id, name FROM users WHERE is_synthetic = 0 AND name = 'Vy' ORDER BY id LIMIT 1"))
    if not row:
        raise service.NotFound("No demo student. Run: python scripts/seed.py")
    return row


@api("/api/llm-log", ["GET"], "Recent Gemini calls: prompt name, latency, success (for documentation)")
async def llm_log(request):
    return {"mode": llm.mode(), "calls": llm.recent_calls()}


@api("/api/safety/check", ["POST"], "Run the safety check on a piece of text")
async def safety_check(request):
    return safety.check((await body(request)).get("text", ""))


# ---------------------------------------------------------------- students

@api("/api/users", ["POST"], "Create a student: {name, interests, college, weekly_capacity, radar_opt_in}")
async def create_user(request):
    b = await body(request)
    result = safety.check(b.get("interests", ""))
    user = service.create_user(b.get("name", ""), b.get("interests", ""), b.get("college", "Undeclared"),
                               float(b.get("weekly_capacity", 25)), bool(b.get("radar_opt_in", True)))
    return {**user, "safety": result}


@api("/api/users/{user_id:int}", ["GET", "PATCH", "DELETE"], "Read, update or delete a student and all their data")
async def user_detail(request):
    if request.method == "DELETE":
        service.delete_user(uid(request))
        return {"deleted": True}
    if request.method == "PATCH":
        return service.update_user(uid(request), **(await body(request)))
    user = service.get_user(uid(request))
    return {**user, "classes": service.get_classes(uid(request)), "checkins": service.get_checkins(uid(request), 14)}


@api("/api/users/{user_id:int}/calendar", ["POST"],
     "Import deadlines: {url} (Canvas Calendar Feed link, used once, never stored) or {ics} (file contents)")
async def import_calendar(request):
    b = await body(request)
    service.get_user(uid(request))
    text = b.get("ics") or (service.fetch_feed(b["url"]) if b.get("url") else None)
    if not text:
        raise service.BadRequest("Send a Canvas feed link or an .ics file")
    return service.import_ics(uid(request), text)


@api("/api/users/{user_id:int}/calendar/sample", ["POST"], "Import the sample Canvas-style feed (demo courses)")
async def import_sample(request):
    service.get_user(uid(request))
    return service.import_ics(uid(request), seed_mod.course_ics(seed_mod.DEMO_COURSES))


@api("/api/users/{user_id:int}/classes", ["GET", "PUT"], "Weekly class times: [{course, weekday, start_hour, end_hour}]")
async def classes(request):
    if request.method == "PUT":
        data = await request.json()
        if isinstance(data, dict) and data.get("sample"):
            data = [{"course": c, "weekday": d, "start_hour": s, "end_hour": e} for c, d, s, e in seed_mod.DEMO_CLASSES]
        if not isinstance(data, list):
            raise service.BadRequest("Send a list of classes")
        return service.set_classes(uid(request), data)
    return service.get_classes(uid(request))


@api("/api/users/{user_id:int}/tasks", ["GET"], "All deadlines with estimates, pace-adjusted hours and status")
async def tasks(request):
    return service.list_tasks(uid(request))


@api("/api/users/{user_id:int}/tasks/{task_id:int}", ["PATCH"],
     "Correct an estimate {user_hours}, log {actual_hours}, or mark {done}")
async def task_update(request):
    b = await body(request)
    return service.update_task(int(request.path_params["task_id"]), uid(request), **b)


@api("/api/users/{user_id:int}/checkins", ["GET", "POST"], "Daily check-in {sleep_hours, stress 1-5, note}")
async def checkins(request):
    if request.method == "POST":
        b = await body(request)
        return service.add_checkin(uid(request), b["sleep_hours"], b["stress"], b.get("note", ""), b.get("day"))
    return service.get_checkins(uid(request))


@api("/api/users/{user_id:int}/forecast", ["GET", "POST"],
     "Weekly stress forecast. POST {extra_lead: {task_id: days}, use_plan: bool, weeks} for what-if")
async def user_forecast(request):
    weeks = int(request.query_params.get("weeks", 7))
    if request.method == "POST":
        b = await body(request)
        extra = {int(k): int(v) for k, v in (b.get("extra_lead") or {}).items() if int(v) > 0}
        return service.user_forecast(uid(request), int(b.get("weeks", weeks)), extra, bool(b.get("use_plan")))
    return service.user_forecast(uid(request), weeks)


@api("/api/users/{user_id:int}/plan", ["GET"], "Study plan: blocks, before/after forecast per week, habit tips")
async def user_plan(request):
    return service.user_plan(uid(request), int(request.query_params.get("weeks", 7)))


@api("/api/users/{user_id:int}/plan.ics", ["GET"], "Download the study plan as an .ics calendar file")
async def user_plan_ics(request):
    return Response(service.plan_ics(uid(request)), media_type="text/calendar",
                    headers={"Content-Disposition": 'attachment; filename="beachwell-study-plan.ics"'})


@api("/api/users/{user_id:int}/events", ["GET"], "De-stress event picks for each Heavy or Overload week")
async def user_events(request):
    return service.user_events(uid(request), int(request.query_params.get("weeks", 7)))


@api("/api/users/{user_id:int}/pace", ["GET"], "Personal pace model: multipliers per assignment type")
async def user_pace(request):
    tasks = service.list_tasks(uid(request))
    model = service.pace_model(tasks)
    logged = [t for t in tasks if t.get("actual_hours")]
    return {"global": round(model.global_mult, 2),
            "by_type": {k: {"multiplier": round(v, 2), "logged": model.counts.get(k, 0)} for k, v in model.by_type.items()},
            "notes": model.describe(), "logged": len(logged),
            "recent": [{"id": t["id"], "title": t["title"], "course": t["course"], "type": t["type"],
                        "estimate": t["base_hours"], "actual": t["actual_hours"]} for t in logged[-12:]]}


# ---------------------------------------------------------------- campus

@api("/api/radar", ["GET"], "Campus Stress Radar: anonymized heatmap, alerts and deadline collisions")
async def radar(request):
    return service.campus_radar()


@api("/api", ["GET"], "This list")
async def index(request):
    return {"endpoints": [{"method": m, "path": p, "description": d} for m, p, d in ROUTES_DOC]}


def _warm_radar() -> None:
    try:
        service.campus_radar()
    except Exception as exc:  # the radar is optional; never block startup
        log.warning("Radar warm-up skipped: %s", exc)


def create_app() -> Starlette:
    routes = [health, demo, llm_log, safety_check, create_user, user_detail, import_calendar, import_sample, classes,
              tasks, task_update, checkins, user_forecast, user_plan, user_plan_ics, user_events, user_pace, radar,
              index]
    frontend = PROJECT_DIR / "frontend"
    if frontend.exists():
        routes.append(Mount("/", StaticFiles(directory=frontend, html=True), name="frontend"))
    @contextlib.asynccontextmanager
    async def lifespan(_app):
        threading.Thread(target=_warm_radar, daemon=True).start()
        yield

    return Starlette(
        routes=routes,
        middleware=[Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])],
        lifespan=lifespan,
    )


db.connect().close()  # make sure the schema exists
app = create_app()

__all__ = ["app", "create_app"]
