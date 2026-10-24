#!/usr/bin/env bash
# AEGIS container / production smoke test. No application secrets: the credentials used are throwaway test values
# generated per run and passed to the container at runtime only.
#   Docker mode (CI):  IMAGE=aegis:ci scripts/container_smoke.sh
#   URL mode (local):  SMOKE_BASE=http://127.0.0.1:8801 SMOKE_LOCKED_BASE=http://127.0.0.1:8802 \
#                      SMOKE_USER=u SMOKE_PASS=p scripts/container_smoke.sh
set -u
PY=${PY:-$(command -v python3 || command -v python)}
FAILS=0
pass() { echo "PASS  $1"; }
fail() { echo "FAIL  $1"; FAILS=$((FAILS + 1)); }
check() { if [ "$2" = "$3" ]; then pass "$1 ($2)"; else fail "$1: expected $3, got $2"; fi; }
code() { curl -s -o /dev/null -w '%{http_code}' --max-time 60 "$@"; }

CIDS=""
C1=""; C2=""
cleanup() { for c in $CIDS; do docker rm -f "$c" >/dev/null 2>&1; done; }
trap cleanup EXIT

wait_up() {
  for _ in $(seq 1 60); do curl -s --max-time 2 "$1/api/health" >/dev/null && return 0; sleep 1; done
  return 1
}

if [ -n "${IMAGE:-}" ]; then
  SMOKE_USER="judge-$(date +%s)"
  SMOKE_PASS="$($PY -c 'import secrets; print(secrets.token_urlsafe(18))')"
  # main container: production mode, login, and a deliberately invalid LLM timeout (must not stop startup)
  C1=$(docker run -d -p 18080:8000 -e AEGIS_BASIC_AUTH_USER="$SMOKE_USER" -e AEGIS_BASIC_AUTH_PASSWORD="$SMOKE_PASS" \
        -e AEGIS_LLM_TIMEOUT=not-a-number "$IMAGE") || { echo "FAIL  container did not start"; exit 1; }
  # second container: no access configuration, listening on a different hosting PORT
  C2=$(docker run -d -p 18081:9123 -e PORT=9123 "$IMAGE") || { echo "FAIL  locked container did not start"; exit 1; }
  CIDS="$C1 $C2"
  SMOKE_BASE=http://127.0.0.1:18080
  SMOKE_LOCKED_BASE=http://127.0.0.1:18081
fi
: "${SMOKE_BASE:?set SMOKE_BASE or IMAGE}" "${SMOKE_USER:?}" "${SMOKE_PASS:?}"
A="-u $SMOKE_USER:$SMOKE_PASS"

if wait_up "$SMOKE_BASE"; then
  pass "app starts in production mode and answers /api/health"
else
  fail "app did not start"
  [ -n "$C1" ] && docker logs "$C1" 2>&1 | tail -30
  exit 1
fi
H=$(curl -s "$SMOKE_BASE/api/health")
echo "$H" | $PY -c 'import sys,json; h=json.load(sys.stdin); sys.exit(0 if h["ok"] and h["env"]=="production" and h["access"]=="basic-auth" and h["simulation_only"] else 1)' \
  && pass "health body: production, basic-auth, simulation_only" || fail "health body unexpected: $H"

check "unauthenticated frontend is rejected" "$(code "$SMOKE_BASE/")" 401
check "unauthenticated API is rejected" "$(code "$SMOKE_BASE/api/scenarios")" 401
check "wrong password is rejected" "$(code -u "$SMOKE_USER:wrong" "$SMOKE_BASE/api/scenarios")" 401
check "authenticated frontend loads" "$(code $A "$SMOKE_BASE/")" 200
JS=$(curl -s $A "$SMOKE_BASE/" | grep -o 'assets/index-[^"]*\.js' | head -1)
[ -n "$JS" ] && pass "index.html references the frontend bundle ($JS)" || fail "index.html has no bundle reference"
check "static bundle is served" "$(code $A "$SMOKE_BASE/$JS")" 200
check "unknown API path is a JSON 404" "$(code $A "$SMOKE_BASE/api/does-not-exist")" 404
CT=$(curl -s $A -o /dev/null -w '%{content_type}' "$SMOKE_BASE/openapi.json")
case "$CT" in *json*) fail "OpenAPI schema is exposed in production ($CT)";; *) pass "OpenAPI schema is not exposed in production";; esac

$PY - "$SMOKE_BASE" "$SMOKE_USER" "$SMOKE_PASS" <<'PYEOF'
import sys, httpx
base, u, p = sys.argv[1:4]
c = httpx.Client(base_url=base, auth=(u, p), timeout=90)
ok = True
def t(name, cond):
    global ok
    print(("PASS  " if cond else "FAIL  ") + name)
    ok = ok and bool(cond)
sh = {x: c.post("/api/shadow/run", json={"plan_id": x}).json() for x in "ABC"}
t("campus A/B/C via Shadow Twin: 5/1/0 of 9 cells breach", [sh[x]["summary"]["violating"] for x in "ABC"] == [5, 1, 0])
t("plan C misses the deadline (180 vs 60 min)", sh["C"]["plan"]["restore_min"] == 180 and sh["C"]["recovery_objective_min"] == 60)
s = c.post("/api/scenarios/stale-degraded/start?seed=42").json()
e = s["episode_id"]
t("stale battery reading is flagged", s["assessment"]["readings"]["battery_soh"]["status"] == "stale")
t("forced Plan A is blocked", c.post(f"/api/episodes/{e}/execute", json={"plan_id": "A", "source": "llm"}).json()["request"]["result"] == "BLOCKED")
d = c.post(f"/api/episodes/{e}/decide").json()
cy = d["record"]["cycles"][-1]
t("gate: A rejected R1, B passed, C rejected R7", {k: v["status"] for k, v in cy["gate"].items()} == {"A": "REJECTED:R1", "B": "PASSED", "C": "REJECTED:R7"})
t("human approval required: nothing executed before approval", d["record"]["pending_approval"]["plan_id"] == "B" and "executed" not in cy)
t("second decision while pending is refused (409)", c.post(f"/api/episodes/{e}/decide").status_code == 409)
t("approval executes", c.post(f"/api/episodes/{e}/approve", json={"approve": True, "operator": "smoke"}).json()["approval"]["result"] == "EXECUTED")
c.post(f"/api/episodes/{e}/faults", json={"kind": "grid_tie_trip"})
t("second fault replans to plan S", c.post(f"/api/episodes/{e}/approve", json={"approve": True}).json()["record"]["cycles"][-1]["selected"] == "S")
t("proof record exports", c.get(f"/api/episodes/{e}/record").status_code == 200)
t("no real violations in the episode", c.post(f"/api/episodes/{e}/close").json()["truth"]["violations"] == [])
ds = c.post("/api/data/sample").json()
t("bundled real NPP data imports 409 points", ds["quality"]["valid_points"] == 409)
rp = c.post(f"/api/data/datasets/{ds['id']}/replay", json={"alpha": 0.3, "seeds_per_hour": 1}).json()
t("replay is labelled SIMULATED and AEGIS has 0 violations", rp["label"].startswith("SIMULATED") and rp["summary"]["D"]["violations"] == 0)
big = ("t,l\n" + "2026-01-01 00:00,1\n" * 400000).encode()
r = c.post("/api/data/import", files={"file": ("big.csv", big)}, data={"source": "s", "timestamp_column": "t", "value_column": "l", "unit": "MW"})
t("oversized upload rejected (413)", r.status_code == 413)
r = c.post("/api/data/import", files={"file": ("x.exe", b"MZ")}, data={"source": "s", "timestamp_column": "a", "value_column": "b", "unit": "MW"})
t("unsupported file type rejected (422)", r.status_code == 422)
ctl = c.post("/api/scenarios/stale-degraded/start?seed=42&controller=llm").json()["record"]["controller"]
t("LLM controller without a key reports deterministic fallback", ctl["requested"] == "llm" and ctl["active"] == "deterministic")
sys.exit(0 if ok else 1)
PYEOF
[ $? -eq 0 ] || FAILS=$((FAILS + 1))

if [ -n "${SMOKE_LOCKED_BASE:-}" ]; then
  if wait_up "$SMOKE_LOCKED_BASE"; then pass "second container honours the hosting PORT"; else fail "locked container did not start"; fi
  check "fail-closed: health reports locked" "$(curl -s "$SMOKE_LOCKED_BASE/api/health" | $PY -c 'import sys,json; print(json.load(sys.stdin)["access"])')" locked
  check "fail-closed: frontend answers 503" "$(code "$SMOKE_LOCKED_BASE/")" 503
  check "fail-closed: API answers 503" "$(code -X POST "$SMOKE_LOCKED_BASE/api/scenarios/stale-degraded/start")" 503
fi

if [ -n "$CIDS" ]; then
  LOGS=$(docker logs "$C1" 2>&1; docker logs "$C2" 2>&1)
  if echo "$LOGS" | grep -qF "$SMOKE_PASS"; then fail "password found in container logs"; else pass "container logs do not contain the password"; fi
  if docker inspect "$IMAGE" | grep -qF "$SMOKE_PASS"; then fail "runtime password found in image metadata"; else pass "image metadata does not contain the runtime password"; fi
  if echo "$LOGS" | grep -qi "traceback"; then fail "unexpected traceback in container logs"; else pass "no tracebacks in container logs"; fi
  if [ -n "$(docker inspect -f '{{.Config.User}}' "$IMAGE")" ]; then pass "image runs as a non-root user"; else fail "image runs as root"; fi
fi

echo
if [ "$FAILS" -eq 0 ]; then echo "SMOKE TEST PASSED"; else echo "SMOKE TEST FAILED ($FAILS)"; exit 1; fi
