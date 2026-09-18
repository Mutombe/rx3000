"""RX-Assistant: the part of the software that knows where the rest of it is.

A pharmacy buys this system and then spends six months finding out what is in
it. The manual nobody reads, the trainer who came for two days, the one person
in the shop who knows where the claim resubmission screen lives. This is meant
to replace all three, and the thing that makes it possible is the atlas: a
generated map of every screen, what it is called, what it needs and which
controls on it can be pointed at.

WHAT IT MAY DO, AND WHAT IT MAY NOT.

It explains and it navigates. It does not act. There is no tool here that
writes anything, and that is a decision rather than an oversight: the worst
outcome of a wrong explanation is somebody checking it, and the worst outcome
of a wrong action is a patient's record. When it is allowed to act, that will
be a separate thing, behind an authorisation, and it will say so.

THE MODEL COMPOSES, THE SERVER DRAWS.

A route like "Dispensary, then the Medicine field, then F12" could be written
as prose and parsed back out. It is not. The model calls `show_route` with the
steps, the server emits a frame, and the interface draws chips that navigate to
the real screen and light up the real control. Parsing prose for structure is
how a feature works in testing and fails on the sentence nobody tried.

TWO MODELS.

Wayfinding is easy work and wants to be fast: Haiku answers "where is the
controlled register" in a fraction of the time and a fraction of the cost. When
a question turns out to want real thinking, the model says so by calling
`think_harder`, and the turn restarts on Opus with everything it has learned so
far. The interface shows that happening rather than hiding it.
"""
from __future__ import annotations

import json
import pathlib
import re
from typing import Any, Callable, Iterator

from . import assistant_data as data
from .ai_service import _get_client, ai_enabled, HOUSE_STYLE

#: Fast, for finding things. The great majority of what gets asked.
WAYFINDING_MODEL = "claude-haiku-4-5-20251001"
#: For the questions that turn out to be about judgement rather than location.
THINKING_MODEL = "claude-opus-5"

#: Where circulars actually come from. A search of the open web for Zimbabwean
#: medicines regulation returns a great deal that is neither Zimbabwean nor
#: current; these are the bodies that publish the real thing.
REGULATOR_DOMAINS = [
    "mcaz.co.zw", "ahfoz.co.zw", "hpa.co.zw", "zimlii.org",
    "health.gov.zw", "who.int",
]

_ATLAS: dict | None = None


def atlas() -> dict:
    """The generated map, read once. See tools/build_atlas.py."""
    global _ATLAS
    if _ATLAS is None:
        path = pathlib.Path(__file__).resolve().parent.parent / "assets" / "atlas.json"
        try:
            _ATLAS = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            # A missing atlas must not take the assistant down with it. It
            # simply knows nothing about the software and says so.
            _ATLAS = {"screens": [], "keys": [], "generated": "not built"}
    return _ATLAS


# ------------------------------------------------------------------ searching
def _score(screen: dict, words: list[str]) -> int:
    """How well a screen answers what somebody typed.

    Weighted by where the word was found, because the name of a screen is a
    much stronger signal than a word buried in its description: somebody asking
    for "stock" means Inventory, not the eleven screens that mention stock.
    """
    label = screen["label"].lower()
    hay = {
        "label": label,
        "section": (screen.get("section") or "").lower(),
        "about": (screen.get("about") or "").lower(),
        "route": screen["route"].lower(),
        "tabs": " ".join(screen.get("tabs") or []).lower(),
        "anchors": " ".join(a["name"] for a in screen.get("anchors") or []).lower(),
    }
    hay["hints"] = " ".join(screen.get("hints") or []).lower()
    weights = {"label": 12, "section": 4, "route": 5, "tabs": 4, "anchors": 3,
               "about": 2, "hints": 3}
    total = 0
    for word in words:
        for field, text in hay.items():
            if word in text:
                total += weights[field]
                if field == "label" and label == word:
                    total += 20            # an exact name beats everything
    return total


def find_screens(query: str, limit: int = 6) -> list[dict]:
    words = [w for w in re.split(r"[^a-z0-9]+", (query or "").lower()) if len(w) > 2]
    if not words:
        return []
    scored = [(s, _score(s, words)) for s in atlas()["screens"]]
    hits = sorted([p for p in scored if p[1] > 0], key=lambda p: -p[1])[:limit]
    return [{
        "route": s["route"],
        "name": s["label"],
        "where": s.get("section") or "",
        "about": s.get("about") or "",
        "in_sidebar": s.get("in_sidebar", False),
        "needs_permission": s.get("needs"),
        "tabs": s.get("tabs") or [],
        "controls": s.get("anchors") or [],
        "keys": s.get("keys") or [],
        "how_it_says_to_use_it": s.get("hints") or [],
    } for s, _ in hits]


def find_actions(query: str) -> list[dict]:
    """The guarded actions, which already carry a name and a reason.

    The step-up catalogue is the best written thing in this codebase about what
    the software lets people do: every entry has a human name, who may approve
    it and WHY it costs a code. "Set a price on a script" is an entry in it, so
    a question phrased exactly that way should find it rather than be guessed
    at, which is what happened before this was wired in.
    """
    from . import stepup

    words = [w for w in re.split(r"[^a-z0-9]+", (query or "").lower()) if len(w) > 2]
    if not words:
        return []
    scored = []
    for action in stepup.catalogue():
        name = (action.get("name") or "").lower()
        # The name carries the weight. A word in the long "why" paragraph is a
        # weak signal, and treating the two alike returned four loosely related
        # actions and missed the one whose name was the question verbatim.
        hit = sum(6 for w in words if w in name)
        hit += sum(3 for w in words if w in (action.get("key") or "").lower())
        hit += sum(1 for w in words if w in (action.get("why") or "").lower())
        if name == (query or "").strip().lower():
            hit += 40
        if hit:
            scored.append((hit, action))
    scored.sort(key=lambda p: -p[0])
    return [{
        "action": a.get("name"),
        "costs_a_code": True,
        "why": (a.get("why") or "")[:260],
        "who_can_approve": a.get("approvers"),
        "can_approve_it_yourself": a.get("self_approval"),
    } for _, a in scored[:3]]


def find_keys(query: str) -> list[dict]:
    """Keys, searched across the screens that bind them and the reference list.

    A screen's own binding wins, and carries the route, because "F3 adds a
    medicine" is only true while you are on the dispensary.
    """
    words = [w for w in re.split(r"[^a-z0-9]+", (query or "").lower()) if len(w) > 1]
    asked = (query or "").strip().lower()
    everywhere: list[dict] = []
    for screen in atlas()["screens"]:
        for key in screen.get("keys") or []:
            everywhere.append({**key, "on": screen["label"], "route": screen["route"]})
    everywhere += [{**k, "on": "", "route": ""} for k in atlas()["keys"]]

    out = []
    for key in everywhere:
        text = f"{key['combo']} {key['label']} {key.get('group', '')}".lower()
        if key["combo"].lower() == asked or any(w in text for w in words):
            out.append(key)
    return out[:10]


# --------------------------------------------------------------------- tools
#: NO `strict` HERE, AND IT IS NOT AN OVERSIGHT.
#:
#: Strict tools would guarantee these shapes exactly, which is what the
#: documentation recommends and what I reached for first. They switch the
#: request into programmatic tool calling, which the fast wayfinding model does
#: not support, and wayfinding is the great majority of what gets asked. A
#: guarantee that costs the model it is meant to run on is not a guarantee.
#:
#: So the interface tolerates instead: a route step needs only a label, every
#: other field is optional, and a step with nothing to click renders as a chip
#: that does not pretend to be a button.
TOOLS: list[dict] = [
    {
        "name": "find_in_app",
        "description": (
            "Search RX5000 for a screen, a tab, a field or a keyboard shortcut. "
            "Use this before answering ANY question about where something is or "
            "how something is done, even when you think you know. It returns the "
            "real route, what the screen is called in the sidebar, what it is "
            "for, which permission it needs, and which controls on it can be "
            "pointed at. Never invent a route: if this does not return it, the "
            "screen does not exist."),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to look for, in the words the person used: "
                                   "'controlled register', 'set a price', 'F12'.",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "show_route",
        "description": (
            "Draw the steps to get somewhere, as chips the person can click. "
            "Use this whenever you are explaining how to do something: it is far "
            "more useful than the same steps written as a sentence, because each "
            "step navigates to the real screen and lights up the real control. "
            "Use the routes and control selectors that find_in_app returned; do "
            "not guess them. Then say anything that needs saying in prose after "
            "it, briefly."),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "What this route achieves, in a few words."},
                "steps": {
                    "type": "array",
                    "description": "In order. Between two and eight of them.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string", "description": "What the person does or sees here."},
                            "go": {"type": "string", "description": "A route from find_in_app, such as /dispense. Omit if this step is not a change of screen."},
                            "click": {"type": "string", "description": "A control selector from find_in_app, such as [data-hk=\"product\"]. Omit if there is nothing to point at."},
                            "key": {"type": "string", "description": "A keyboard shortcut for this step, such as F12."},
                            "does": {"type": "boolean", "description": "True when this step CHANGES something rather than navigating."},
                        },
                        "required": ["label"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["title", "steps"],
            "additionalProperties": False,
        },
    },
    {
        "name": "show_diagram",
        "description": (
            "Draw a diagram when the shape of something is the answer: how a "
            "claim moves between states, what happens to stock when a script is "
            "dispensed, which screens feed which. Mermaid source. Prefer a "
            "route over a diagram for 'how do I', and a diagram over prose for "
            "'how does this work'."),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "mermaid": {
                    "type": "string",
                    "description": "Mermaid source. Lay it out SIDEWAYS: "
                                   "'flowchart LR', or 'stateDiagram-v2' with "
                                   "'direction LR' on its first line. Top to "
                                   "bottom produces a thousand pixels of column "
                                   "that nobody reads on a till. At most eight "
                                   "nodes, short labels, no styling.",
                },
            },
            "required": ["title", "mermaid"],
            "additionalProperties": False,
        },
    },
    {
        "name": "look_up_medicine",
        "description": (
            "Look up a medicine in THIS pharmacy: its schedule, pack size, what "
            "is on this branch's shelf, its reorder level and its price. Use it "
            "whenever somebody names a medicine. Read only."),
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "Part of the name is enough."}},
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "usage_history",
        "description": (
            "How much of a medicine has actually left the shelf, month by "
            "month. Use it for 'how fast does this move', 'should I order' and "
            "anything about demand. Read only."),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "months": {"type": "integer", "description": "1 to 24. Six if unsure."},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "how_is_trade",
        "description": (
            "What this pharmacy has taken over a period, how many sales and "
            "scripts, and its best sellers. Needs permission to see money and "
            "will say so if the person has none. Read only."),
        "input_schema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "description": "1 to 365. Seven if unsure."}},
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "what_is_low",
        "description": (
            "Which lines are at or below their reorder level on this branch's "
            "shelf. Read only."),
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "Up to 40."}},
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "think_harder",
        "description": (
            "Hand this question to the larger model. Call it when the question "
            "is not about where something is but about judgement, analysis, "
            "writing, or a decision with trade-offs. Do not call it for anything "
            "find_in_app can answer."),
        "input_schema": {
            "type": "object",
            "properties": {
                "why": {"type": "string", "description": "One line: what makes this need more thought."},
            },
            "required": ["why"],
            "additionalProperties": False,
        },
    },
]

#: What the interface says while a tool runs. Written for a dispenser with a
#: patient at the counter, not for a developer reading a log.
SAYING = {
    "find_in_app": "Looking that up in the system",
    "show_route": "Drawing the steps",
    "show_diagram": "Drawing it out",
    "look_up_medicine": "Checking that medicine",
    "usage_history": "Reading what has moved",
    "how_is_trade": "Reading the takings",
    "what_is_low": "Checking what is low",
    "think_harder": "Asking the bigger model",
    "web_search": "Checking the regulator",
}


SYSTEM = """You are RX-Assistant, built into RX5000, a pharmacy system used in \
Zimbabwe. You are talking to somebody working behind a pharmacy counter: a \
dispenser, a pharmacist, a manager or a cashier. Often there is a patient \
waiting in front of them.

WHAT YOU ARE FOR
Telling people where things are in this software, how to do them, what things \
mean, and what this pharmacy's own figures say. You know the software through \
find_in_app and the shop through the lookup tools, and you know nothing about \
either otherwise. Look things up before you answer, every time. A route you \
invented is worse than saying you could not find it, because they will go \
looking for a screen that does not exist, and a figure you invented is worse \
still because they will act on it.

THE FIGURES ARE THEIRS, AND SO ARE THE LIMITS
The lookup tools run as the person you are talking to, under their own \
permissions and on their own branch. When one comes back refused, say plainly \
that their account cannot see that and what it would take. Do not work around \
it, do not estimate the answer out of something else, and never suggest they \
use somebody else's login.

HOW TO ANSWER
Call a tool first, silently. Never announce one, before or after: not "let me \
look that up", not "now I have the screens", not "let me draw you a diagram". \
Every one of those describes something the reader is already watching happen.

Two kinds of question, two kinds of answer. "Where is it" and "how do I" want \
a route: draw it with show_route, because the chips take them there, which is \
the whole point. "How much", "how fast", "what is low", "what have we taken" \
want the FIGURE: call the lookup tool and answer with the number. Somebody \
asking how fast a medicine moves has been sent to a screen to work it out for \
themselves once too often already; you can see it, so tell them, and mention \
the screen afterwards only if it is worth opening.

Keep the prose short either way. They are reading this standing up.

Say when a screen needs a permission they may not have, because "it is not on \
my sidebar" is the commonest reason somebody cannot find something.

WHAT YOU MUST NOT DO
You cannot change anything in the system and must never imply that you can or \
that you have. You do not give clinical advice: dosing, interactions and \
suitability are for the pharmacist and for the screening the software already \
does. You may explain where those checks live and what they mean.

If you do not know, say so in one sentence and say what would answer it.
"""


#: The data tools, each taking the request's own session and user. Kept
#: together so it is obvious at a glance that every one of them does.
_DATA: dict[str, Any] = {
    "look_up_medicine": lambda db, u, a: data.look_up_medicine(db, u, str(a.get("name", ""))),
    "usage_history": lambda db, u, a: data.usage_history(
        db, u, str(a.get("name", "")), int(a.get("months") or 6)),
    "how_is_trade": lambda db, u, a: data.how_is_trade(db, u, int(a.get("days") or 7)),
    "what_is_low": lambda db, u, a: data.what_is_low(db, u, int(a.get("limit") or 15)),
}


def _said_about(name: str, payload: dict) -> str:
    """One line for the reader about what a lookup came back with.

    A refusal says so out loud rather than disappearing into the answer: "you
    are not allowed to see that" is a thing somebody needs to know about their
    own account, not a gap in a sentence.
    """
    if payload.get("refused"):
        return "not allowed"
    if name == "look_up_medicine":
        n = payload.get("found", 0)
        return f"{n} found" if n else "nothing matched"
    if name == "usage_history":
        return f"{payload.get('total_out', 0)} units over {len(payload.get('months', []))} months"
    if name == "how_is_trade":
        return f"{payload.get('sales', 0)} sales"
    if name == "what_is_low":
        return f"{payload.get('count', 0)} lines low"
    return "done"


def _tool_result(name: str, payload: Any) -> dict:
    return {"type": "tool_result", "tool_use_id": name, "content": json.dumps(payload)}


def run(question: str, history: list[dict] | None = None, *,
        web: bool = True, db=None, user=None) -> Iterator[dict]:
    """Answer one question, yielding frames as it goes.

    Frames are dictionaries the router serialises: `phase`, `tool` (one is
    starting), `tool_done`, `delta` (text), `route`, `diagram`, `model` (the
    turn moved to a different one), `error`, `done`. The frontend ignores frame
    types it does not know, so this can grow without breaking the screens that
    already read it.
    """
    if not ai_enabled():
        yield {"type": "error", "message": "The assistant is switched off: no API key is set."}
        return

    client = _get_client()

    def toolset(for_model: str) -> list[dict]:
        """The tools, which are not the same on both models.

        The web search tool is a server tool and requires programmatic tool
        calling, which the fast wayfinding model does not support: attaching it
        there fails the whole request with a 400 rather than degrading. That is
        the right split anyway. Checking a circular is precisely the kind of
        question that should have gone to the bigger model, so it arrives with
        the search available and the fast model hands over to reach it.
        """
        tools = list(TOOLS)
        if web and for_model == THINKING_MODEL:
            tools.append({
                "type": "web_search_20260209",
                "name": "web_search",
                "max_uses": 3,
                "allowed_domains": REGULATOR_DOMAINS,
            })
        return tools

    messages: list[dict] = list(history or [])
    messages.append({"role": "user", "content": question})
    model = WAYFINDING_MODEL
    answered = False

    # Bounded. Every pass is a paid round trip, and a loop that cannot end is
    # a bill that cannot end.
    for _pass in range(6):
        yield {"type": "phase", "phase": "thinking"}
        # THE FIRST PASS MUST CALL A TOOL.
        #
        # Asked politely in the prompt, Haiku still opened with "I'll find
        # where you set a price on a script", which is a sentence describing
        # the spinner the reader is already looking at. Forcing a tool on the
        # opening pass makes the preamble impossible rather than discouraged,
        # and it enforces the rule that matters anyway: look it up before you
        # answer. Afterwards it chooses for itself.
        # No `disable_parallel_tool_use` here: the API refuses it alongside
        # strict tools, and schema conformance is worth more than one call per
        # turn. The loop below already handles a pass that calls several.
        choice: dict = {"type": "any"} if _pass == 0 else {"type": "auto"}
        try:
            with client.messages.stream(
                model=model,
                max_tokens=4000,
                system=SYSTEM + HOUSE_STYLE,
                tools=toolset(model),
                tool_choice=choice,
                messages=messages,
            ) as stream:
                for text in stream.text_stream:
                    answered = True
                    yield {"type": "delta", "text": text}
                final = stream.get_final_message()
        except Exception as exc:                            # noqa: BLE001
            yield {"type": "error", "message": f"The assistant could not answer: {exc}"}
            return

        calls = [b for b in final.content if getattr(b, "type", "") == "tool_use"]
        if not calls:
            break

        messages.append({"role": "assistant", "content": final.content})
        results = []
        escalate = False
        for call in calls:
            name, args = call.name, (call.input or {})
            yield {"type": "tool", "name": name,
                   "say": SAYING.get(name, "Working on it")}

            if name == "find_in_app":
                query = str(args.get("query", ""))
                payload = {
                    "screens": find_screens(query),
                    "keys": find_keys(query),
                    "guarded_actions": find_actions(query),
                }
                found = len(payload["screens"])
                yield {"type": "tool_done", "name": name,
                       "say": f"{found} screen{'' if found == 1 else 's'} found"
                              if found else "nothing matched"}
            elif name == "show_route":
                payload = {"drawn": True}
                yield {"type": "route", "title": args.get("title", ""),
                       "steps": args.get("steps", [])}
                yield {"type": "tool_done", "name": name, "say": "drawn"}
            elif name == "show_diagram":
                payload = {"drawn": True}
                yield {"type": "diagram", "title": args.get("title", ""),
                       "mermaid": args.get("mermaid", "")}
                yield {"type": "tool_done", "name": name, "say": "drawn"}
            elif name in ("look_up_medicine", "usage_history",
                          "how_is_trade", "what_is_low"):
                # Every one of these runs as the person asking, through the
                # same permission checks the screens go through. Without a
                # session there is nobody to run as, and the honest answer is
                # that it cannot look.
                if db is None or user is None:
                    payload = {"refused": "No session, so nothing can be looked up."}
                    yield {"type": "tool_done", "name": name, "say": "not available"}
                else:
                    payload = _DATA[name](db, user, args)
                    yield {"type": "tool_done", "name": name,
                           "say": _said_about(name, payload)}
            elif name == "think_harder":
                escalate = True
                payload = {"handed_over": True}
                yield {"type": "tool_done", "name": name, "say": args.get("why", "")}
            else:
                payload = {"note": "That tool is not available."}
                yield {"type": "tool_done", "name": name, "say": "not available"}

            results.append({
                "type": "tool_result",
                "tool_use_id": call.id,
                "content": json.dumps(payload),
            })

        messages.append({"role": "user", "content": results})
        if escalate and model != THINKING_MODEL:
            model = THINKING_MODEL
            yield {"type": "model", "model": "thinking",
                   "say": "Thinking about this properly"}

    if not answered:
        yield {"type": "delta",
               "text": "I could not find an answer to that in RX5000."}
    yield {"type": "done"}
