"""AEGIS hackathon deck (16:9) built from real app screenshots and committed results."""
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Inches, Pt

S = Path(__file__).parent / "out" / "shots"
OUT = "C:/Users/ayush/Downloads/AEGIS_Final_Deck_v2.pptx"
INK, MUTED, BRAND, TEAL = RGBColor(0x0B, 0x12, 0x26), RGBColor(0x54, 0x60, 0x79), RGBColor(0x4A, 0x43, 0xD9), RGBColor(0x0E, 0x8F, 0x94)
OK, BAD, BG = RGBColor(0x05, 0x96, 0x69), RGBColor(0xE1, 0x1D, 0x48), RGBColor(0xF4, 0xF6, 0xFB)

prs = Presentation()
prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
BLANK = prs.slide_layouts[6]


def slide(bg=BG):
    s = prs.slides.add_slide(BLANK)
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = bg
    return s


def text(s, x, y, w, h, t, size=18, color=INK, bold=False, align=None):
    tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    for i, line in enumerate(t.split("\n")):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = line
        p.font.size, p.font.color.rgb, p.font.bold, p.font.name = Pt(size), color, bold, "Segoe UI"
        if align:
            p.alignment = align
        p.space_after = Pt(6)
    return tb


def bar(s, color=BRAND):
    r = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, Inches(0.12))
    r.fill.solid()
    r.fill.fore_color.rgb = color
    r.line.fill.background()


def title(s, kicker, t):
    bar(s)
    text(s, 0.6, 0.35, 12, 0.4, kicker.upper(), 12, BRAND, True)
    text(s, 0.6, 0.7, 12.2, 0.9, t, 30, INK, True)


def card(s, x, y, w, h, head, body, accent=BRAND, big=None):
    r = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    r.adjustments[0] = 0.08
    r.fill.solid()
    r.fill.fore_color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    r.line.color.rgb = RGBColor(0xDC, 0xE1, 0xEC)
    a = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(0.08), Inches(h))
    a.fill.solid()
    a.fill.fore_color.rgb = accent
    a.line.fill.background()
    yy = y + 0.15
    if big:
        text(s, x + 0.25, yy, w - 0.4, 0.8, big, 34, accent, True)
        yy += 0.8
    text(s, x + 0.25, yy, w - 0.4, 0.45, head, 15, INK, True)
    text(s, x + 0.25, yy + 0.42, w - 0.4, h - (yy - y) - 0.5, body, 12, MUTED)


def shot(s, name, x, y, w):
    s.shapes.add_picture(str(S / name), Inches(x), Inches(y), width=Inches(w))


# 1 Title
s = slide(INK)
bar(s, TEAL)
text(s, 0.8, 1.2, 11, 0.5, "CGI AGENTOPS 2026 · ENERGY & UTILITIES · TEAM JUGAAD CODERS", 14, RGBColor(0xA9, 0xB0, 0xF5), True)
text(s, 0.8, 1.9, 11.5, 1.2, "AEGIS 3.0", 66, RGBColor(0xFF, 0xFF, 0xFF), True)
text(s, 0.8, 3.1, 11.5, 0.8, "Counterfactual Safety Agent for Reliable Infrastructure Recovery", 26, RGBColor(0xDD, 0xE3, 0xF3))
text(s, 0.8, 4.3, 11.5, 0.8, "Know the risk before you commit to recovery.", 24, RGBColor(0x5E, 0xEA, 0xD4), True)
text(s, 0.8, 6.3, 12, 0.5, "0 hard-limit violations  ·  2× safe recoveries  ·  independent safety gate  ·  human in command",
     14, RGBColor(0xA9, 0xB0, 0xF5))

# 2 Problem
s = slide()
title(s, "The problem", "The fastest recovery plan can look safe and still fail")
text(s, 0.6, 1.8, 6.2, 4.5,
     "A campus water pump fails. The backup pump runs on a battery.\n\n"
     "The battery-health reading is 47 minutes old (limit: 10).\n\n"
     "If the battery has degraded, the fastest plan drains it below the 30% reserve that critical services depend on.\n\n"
     "Most agents trust the reading and act. In our benchmark, that caused 114–134 hard-limit violations.", 17, INK)
shot(s, "0_hero.png", 7.1, 1.8, 5.7)

# 3 Solution
s = slide()
title(s, "The solution", "AEGIS tries to break its own plan before it acts")
items = [("Counterfactual testing", "Every plan rolled forward under every plausible hidden battery state. Concrete counterexamples.", BRAND),
         ("Value-of-information", "A diagnostic runs only when its result could change the decision.", TEAL),
         ("Independent safety gate", "Seven deterministic rules (R1–R7), separate from the planner and any AI. Fails closed.", BAD),
         ("Human in command", "Consequential actions need operator approval; the gate re-checks on fresh data first.", OK),
         ("Verify, replan, abstain", "Runtime monitor, restoration checks, replanning after new faults, abstention when nothing is safe.", BRAND),
         ("Auditable", "Every decision exports as a reproducible Decision Proof Record.", TEAL)]
for i, (h, b, c) in enumerate(items):
    card(s, 0.6 + (i % 3) * 4.1, 1.8 + (i // 3) * 2.6, 3.9, 2.4, h, b, c)

# 4 Plans
s = slide()
title(s, "Decision in action", "Plan A is fast. Plan C is safe. Only Plan B is both.")
shot(s, "1_plans.png", 0.6, 1.7, 8.2)
card(s, 9.1, 1.7, 3.7, 1.6, "A · Rejected (R1)", "12 min, but breaches the 30% reserve in 5 of 9 battery conditions.", BAD)
card(s, 9.1, 3.45, 3.7, 1.6, "B · Passed", "25 min, holds the reserve. Still needs human approval.", OK)
card(s, 9.1, 5.2, 3.7, 1.6, "C · Rejected (R7)", "Safe, but 180 min against a 60-min objective.", BAD)

# 5 Governance
s = slide()
title(s, "Responsible AI · governance", "No AI and no shortcut can bypass the gate or the human")
shot(s, "2_gate.png", 0.6, 1.7, 6.1)
shot(s, "3_approval.png", 6.9, 1.7, 5.9)
text(s, 0.6, 5.3, 12.2, 1.8,
     "• A forced Plan A (from an operator or an LLM) is BLOCKED by rule R1. Counterexample: 21% < 30% on a degraded battery.\n"
     "• Plan B waits for approval; the gate re-checks before execution. Restored in 29 sim-min, verified.\n"
     "• Second fault (grid trip) → automatic replan to load-shedding plan S → approval again.", 15, INK)

# 6 Shadow + real data
s = slide()
title(s, "See the risk · real data", "Shadow Twin what-ifs and real national demand data")
shot(s, "4_shadow.png", 0.6, 1.7, 6.1)
shot(s, "5_realdata.png", 6.9, 1.7, 5.9)
text(s, 0.6, 5.3, 6.1, 1.8, "Shadow Twin: any plan across 9 what-if battery conditions. Green holds, red breaches.", 15, INK)
text(s, 6.9, 5.3, 5.9, 1.8, "409 real records from India's National Power Portal, replayed as stress: AEGIS 0 violations; basic agent 72 of 72.", 15, INK)

# 7 Results
s = slide()
title(s, "Business value · ROI", "Zero unsafe restorations, twice the safe recoveries")
card(s, 0.6, 1.8, 3.9, 2.5, "Hard-limit violations", "AEGIS vs 114 (fixed rules) and 134 (basic agent), 220 episodes per arm.", OK, "0")
card(s, 4.7, 1.8, 3.9, 2.5, "Safe in-time recoveries", "vs 86 for each baseline: 2× the safe recoveries.", BRAND, "172")
card(s, 8.8, 1.8, 3.9, 2.5, "Stress suite violations", "Unexpected drain, sensor bias, mid-plan faults. Baselines: 153 each.", TEAL, "0")
card(s, 0.6, 4.55, 3.9, 2.4, "Correct abstentions", "When no safe plan exists, AEGIS never executes an unsafe one.", OK, "40/40")
card(s, 4.7, 4.55, 3.9, 2.4, "Fewer wasted tests", "161 unneeded diagnostics vs 470 when testing everything.", BRAND, "−66%")
card(s, 8.8, 4.55, 3.9, 2.4, "Pre-registered hypotheses", "H1, H3, H4 supported; every result published as measured.", TEAL, "3 of 4")

# 8 Architecture / reusability
s = slide()
title(s, "Architecture · reusability · MVP", "Built to be trusted, reused and deployed")
text(s, 0.6, 1.8, 6.4, 5,
     "Pipeline\n"
     "telemetry → assessor → hidden-state beliefs → counterfactual evaluator → diagnostic planner → "
     "independent safety gate → human approval → gate re-check → executor + runtime monitor → verifier → replan / abstain → proof record\n\n"
     "Reusable\n"
     "Plans, limits and priors live in scenario JSON: a new campus, hospital or water utility changes configuration, not code.\n\n"
     "LLM-ready\n"
     "Optional Claude tool controller chooses the steps; the gate, approval and executor stay in charge.", 15, INK)
card(s, 7.3, 1.8, 5.5, 5.1, "MVP readiness",
     "• 138 automated tests (every gate rule, fail-closed, bypass attempts, 200-case property test)\n"
     "• Container CI: real Docker image built and smoke-tested on every push\n"
     "• Deployed on Render with login and fail-closed access\n"
     "• Reproducible: same seed, same digest\n"
     "• React + TypeScript dashboard, FastAPI backend", BRAND)

# Impact & benefits
s = slide()
title(s, "Impact · benefits", "Who gains, and how")
ib = [("Critical services stay on", "Hospitals, labs and water keep their battery reserve: 0 unsafe restorations in every test we ran.", OK),
      ("Fewer costly failures", "Avoids battery damage, equipment over-stress and repeat outages that unsafe quick fixes cause.", BAD),
      ("Faster, confident operators", "Clear A/B/C comparison and one-click approval instead of guessing under pressure.", BRAND),
      ("Lower diagnostic cost", "66% fewer unnecessary tests: crews only check what can change the decision.", TEAL),
      ("Audit & compliance ready", "Every decision has a proof record: who approved, what was checked, why.", BRAND),
      ("Scales across sites", "Campuses, hospitals, water utilities and microgrids: new site = new configuration, not new code.", OK)]
for i, (h, b, c) in enumerate(ib):
    card(s, 0.6 + (i % 3) * 4.1, 1.8 + (i // 3) * 2.6, 3.9, 2.4, h, b, c)

# 9 Roadmap + close
s = slide(INK)
bar(s, TEAL)
text(s, 0.8, 0.8, 11.5, 0.6, "ROADMAP", 14, RGBColor(0xA9, 0xB0, 0xF5), True)
steps = [("Simulation", "✓ done"), ("Historical replay", "✓ done"), ("Shadow mode on live telemetry", "next"), ("Supervised pilot", "then"),
         ("Production", "goal")]
for i, (h, b) in enumerate(steps):
    x = 0.8 + i * 2.45
    r = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(1.6), Inches(2.25), Inches(1.4))
    r.fill.solid()
    r.fill.fore_color.rgb = RGBColor(0x1E, 0x27, 0x45) if i > 1 else RGBColor(0x0E, 0x8F, 0x94)
    r.line.fill.background()
    text(s, x + 0.15, 1.75, 2.0, 0.7, h, 15, RGBColor(0xFF, 0xFF, 0xFF), True)
    text(s, x + 0.15, 2.45, 2.0, 0.4, b, 12, RGBColor(0xDD, 0xE3, 0xF3))
text(s, 0.8, 3.8, 11.8, 1.2, "AEGIS: find the failure before you commit to the fix.", 38, RGBColor(0xFF, 0xFF, 0xFF), True)
text(s, 0.8, 5.6, 11.8, 1.0, "github.com/ParthavSatvik/AEGIS-3.0  ·  aegis-3-oyzv.onrender.com\nTeam Jugaad Coders · Thank you", 16,
     RGBColor(0xA9, 0xB0, 0xF5))

prs.save(OUT)
print("saved", OUT, len(prs.slides), "slides")
