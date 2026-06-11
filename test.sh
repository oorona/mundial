#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Baseline Framework — Test Runner
# ─────────────────────────────────────────────────────────────────────────────
# Usage:
#   ./test.sh                          # interactive menu
#   ./test.sh all                      # run everything
#   ./test.sh frontend                 # frontend unit tests (Vitest)
#   ./test.sh backend                  # backend unit tests (pytest)
#   ./test.sh bot                      # bot unit tests (pytest)
#   ./test.sh integration              # all 8 integration suites (needs Docker stack)
#   ./test.sh integration:01,03,07     # specific integration suites
#   ./test.sh frontend backend         # multiple groups
#
# Environment variables:
#   TEST_API_TOKEN   Bearer token for L2+ authenticated integration tests
#   GATEWAY_URL      Override gateway URL (default: http://localhost)
#   BACKEND_URL      Override backend URL (default: http://localhost:8000)
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Colors & Styles ──────────────────────────────────────────────────────────
RESET='\033[0m'
BOLD='\033[1m'
DIM='\033[2m'
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
WHITE='\033[0;37m'
BOLD_RED='\033[1;31m'
BOLD_GREEN='\033[1;32m'
BOLD_CYAN='\033[1;36m'
BOLD_WHITE='\033[1;37m'

# ── Suite metadata ───────────────────────────────────────────────────────────
SUITE_LABELS=(
    "01 · Health & Connectivity"
    "02 · Security Headers"
    "03 · Authentication"
    "04 · Security Levels"
    "05 · Rate Limits"
    "07 · Database"
    "08 · LLM Endpoints"
    "09 · Audit Log"
    "10 · Instrumentation"
)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Result tracking ──────────────────────────────────────────────────────────
declare -a RESULT_NAMES=()
declare -a RESULT_STATUS=()   # pass | fail | skip | error
declare -a RESULT_TIMES=()
declare -a RESULT_DETAILS=()

record_result() {
    local name="$1" status="$2" elapsed="$3" detail="${4:-}"
    RESULT_NAMES+=("$name")
    RESULT_STATUS+=("$status")
    RESULT_TIMES+=("$elapsed")
    RESULT_DETAILS+=("$detail")
}

# ── Helpers ───────────────────────────────────────────────────────────────────
rule() {
    local label="${1:-}"
    local width=62
    if [[ -n "$label" ]]; then
        local pad=$(( (width - ${#label} - 2) / 2 ))
        local line
        printf -v line '%*s' "$pad" ''
        printf "\n${BOLD_CYAN}%s ${BOLD_WHITE}%s${BOLD_CYAN} %s${RESET}\n" \
            "$(printf '─%.0s' $(seq 1 $pad))" "$label" \
            "$(printf '─%.0s' $(seq 1 $pad))"
    else
        printf "${DIM}$(printf '─%.0s' $(seq 1 $width))${RESET}\n"
    fi
}

check_cmd() {
    command -v "$1" &>/dev/null
}

elapsed_since() {
    local start="$1"
    local end
    end=$(date +%s%3N)
    echo $(( end - start ))
}

fmt_ms() {
    local ms="$1"
    if (( ms < 1000 )); then
        printf "%dms" "$ms"
    else
        printf "%.1fs" "$(echo "scale=1; $ms/1000" | bc)"
    fi
}

# ── Individual runners ────────────────────────────────────────────────────────

run_frontend() {
    rule "Frontend  (Vitest)"
    if ! check_cmd npm; then
        echo -e "  ${YELLOW}⚠ npm not found — skipping${RESET}"
        record_result "Frontend (Vitest)" "skip" "0" "npm not found"
        return
    fi
    if [[ ! -d "$SCRIPT_DIR/frontend" ]]; then
        echo -e "  ${YELLOW}⚠ frontend/ directory not found — skipping${RESET}"
        record_result "Frontend (Vitest)" "skip" "0" "frontend/ not found"
        return
    fi

    local start
    start=$(date +%s%3N)
    local exit_code=0
    local runner_output
    runner_output=$(cd "$SCRIPT_DIR/frontend" && npm run test 2>&1) || exit_code=$?
    echo "$runner_output"

    local elapsed
    elapsed=$(elapsed_since "$start")

    # Parse "N passed" from Vitest summary line
    local counts=""
    local passed failed skipped
    passed=$(echo "$runner_output" | grep -oP '\d+(?= passed)' | tail -1 || true)
    failed=$(echo "$runner_output" | grep -oP '\d+(?= failed)'  | tail -1 || true)
    skipped=$(echo "$runner_output" | grep -oP '\d+(?= skipped)'| tail -1 || true)
    [[ -n "$passed"  ]] && counts="${passed} passed"
    [[ -n "$failed"  && "$failed"  != "0" ]] && counts="${counts}  ${failed} failed"
    [[ -n "$skipped" && "$skipped" != "0" ]] && counts="${counts}  ${skipped} skipped"

    if (( exit_code == 0 )); then
        echo -e "\n  ${BOLD_GREEN}✓ Frontend tests passed${RESET} $(fmt_ms $elapsed)"
        record_result "Frontend (Vitest)" "pass" "$elapsed" "$counts"
    else
        echo -e "\n  ${BOLD_RED}✗ Frontend tests failed${RESET} $(fmt_ms $elapsed)"
        record_result "Frontend (Vitest)" "fail" "$elapsed" "${counts:-exit code $exit_code}"
    fi
}

run_backend() {
    rule "Backend  (pytest — unit)"
    if ! check_cmd docker; then
        echo -e "  ${YELLOW}⚠ docker not found — skipping${RESET}"
        record_result "Backend (pytest)" "skip" "0" "docker not found"
        return
    fi
    if [[ ! -d "$SCRIPT_DIR/backend/tests" ]]; then
        echo -e "  ${YELLOW}⚠ backend/tests/ not found — skipping${RESET}"
        record_result "Backend (pytest)" "skip" "0" "backend/tests/ not found"
        return
    fi

    # Check the backend container is running
    if ! docker compose -f "$SCRIPT_DIR/docker-compose.yml" ps --status running backend 2>/dev/null | grep -q backend; then
        echo -e "  ${YELLOW}⚠ backend container not running — start the stack first:${RESET}"
        echo -e "  ${DIM}  docker compose up -d${RESET}"
        record_result "Backend (pytest)" "skip" "0" "backend container not running"
        return
    fi

    local start
    start=$(date +%s%3N)
    local exit_code=0
    local runner_output
    runner_output=$(docker compose -f "$SCRIPT_DIR/docker-compose.yml" exec backend \
        python -m pytest tests/ -v --tb=short 2>&1) || exit_code=$?
    echo "$runner_output"

    local elapsed
    elapsed=$(elapsed_since "$start")

    # Parse "N passed" from pytest summary line
    local counts=""
    local passed failed skipped
    passed=$(echo "$runner_output" | grep -oP '\d+(?= passed)' | tail -1 || true)
    failed=$(echo "$runner_output" | grep -oP '\d+(?= failed)'  | tail -1 || true)
    skipped=$(echo "$runner_output" | grep -oP '\d+(?= skipped)'| tail -1 || true)
    [[ -n "$passed"  ]] && counts="${passed} passed"
    [[ -n "$failed"  && "$failed"  != "0" ]] && counts="${counts}  ${failed} failed"
    [[ -n "$skipped" && "$skipped" != "0" ]] && counts="${counts}  ${skipped} skipped"

    if (( exit_code == 0 )); then
        echo -e "\n  ${BOLD_GREEN}✓ Backend tests passed${RESET} $(fmt_ms $elapsed)"
        record_result "Backend (pytest)" "pass" "$elapsed" "$counts"
    else
        echo -e "\n  ${BOLD_RED}✗ Backend tests failed${RESET} $(fmt_ms $elapsed)"
        record_result "Backend (pytest)" "fail" "$elapsed" "${counts:-exit code $exit_code}"
    fi
}

run_bot() {
    rule "Bot  (pytest — unit)"
    if ! check_cmd docker; then
        echo -e "  ${YELLOW}⚠ docker not found — skipping${RESET}"
        record_result "Bot (pytest)" "skip" "0" "docker not found"
        return
    fi
    if [[ ! -d "$SCRIPT_DIR/bot/tests" ]]; then
        echo -e "  ${YELLOW}⚠ bot/tests/ not found — skipping${RESET}"
        record_result "Bot (pytest)" "skip" "0" "bot/tests/ not found"
        return
    fi

    # Check the bot container is running
    if ! docker compose -f "$SCRIPT_DIR/docker-compose.yml" ps --status running bot 2>/dev/null | grep -q bot; then
        echo -e "  ${YELLOW}⚠ bot container not running — start the stack first:${RESET}"
        echo -e "  ${DIM}  docker compose up -d${RESET}"
        record_result "Bot (pytest)" "skip" "0" "bot container not running"
        return
    fi

    local start
    start=$(date +%s%3N)
    local exit_code=0
    local runner_output
    runner_output=$(docker compose -f "$SCRIPT_DIR/docker-compose.yml" exec bot \
        python -m pytest tests/ -v --tb=short 2>&1) || exit_code=$?
    echo "$runner_output"

    local elapsed
    elapsed=$(elapsed_since "$start")

    # Parse "N passed" from pytest summary line
    local counts=""
    local passed failed skipped
    passed=$(echo "$runner_output" | grep -oP '\d+(?= passed)' | tail -1 || true)
    failed=$(echo "$runner_output" | grep -oP '\d+(?= failed)'  | tail -1 || true)
    skipped=$(echo "$runner_output" | grep -oP '\d+(?= skipped)'| tail -1 || true)
    [[ -n "$passed"  ]] && counts="${passed} passed"
    [[ -n "$failed"  && "$failed"  != "0" ]] && counts="${counts}  ${failed} failed"
    [[ -n "$skipped" && "$skipped" != "0" ]] && counts="${counts}  ${skipped} skipped"

    if (( exit_code == 0 )); then
        echo -e "\n  ${BOLD_GREEN}✓ Bot tests passed${RESET} $(fmt_ms $elapsed)"
        record_result "Bot (pytest)" "pass" "$elapsed" "$counts"
    else
        echo -e "\n  ${BOLD_RED}✗ Bot tests failed${RESET} $(fmt_ms $elapsed)"
        record_result "Bot (pytest)" "fail" "$elapsed" "${counts:-exit code $exit_code}"
    fi
}

run_integration() {
    local suites_filter="${1:-}"  # e.g. "01,03,07" or empty = all

    if [[ -n "$suites_filter" ]]; then
        rule "Integration  (suites: $suites_filter)"
    else
        rule "Integration  (all suites)"
    fi

    if ! check_cmd docker; then
        echo -e "  ${YELLOW}⚠ docker not found — skipping integration tests${RESET}"
        record_result "Integration" "skip" "0" "docker not found"
        return
    fi

    # Auto-load .env.test.local if present (gitignored — holds tokens/IDs)
    local env_file="$SCRIPT_DIR/.env.test.local"
    if [[ -f "$env_file" ]]; then
        # Source it so variables are available for the -e flags below,
        # and also pass --env-file so docker compose interpolates ${VAR} in
        # docker-compose.test.yml from the file.
        set -a; source "$env_file"; set +a
    fi

    # Build docker compose command
    local compose_cmd=("docker" "compose"
        "-f" "$SCRIPT_DIR/docker-compose.yml"
        "-f" "$SCRIPT_DIR/docker-compose.test.yml"
    )
    [[ -f "$env_file" ]] && compose_cmd+=("--env-file" "$env_file")
    compose_cmd+=("run" "--rm")

    # Pass env vars (shell env takes precedence over .env.test.local values)
    [[ -n "${TEST_API_TOKEN:-}" ]]  && compose_cmd+=("-e" "TEST_API_TOKEN=$TEST_API_TOKEN")
    [[ -n "${TEST_GUILD_ID:-}" ]]   && compose_cmd+=("-e" "TEST_GUILD_ID=$TEST_GUILD_ID")
    [[ -n "${TEST_USER_ID:-}" ]]    && compose_cmd+=("-e" "TEST_USER_ID=$TEST_USER_ID")
    [[ -n "${TEST_ROLE_ID:-}" ]]    && compose_cmd+=("-e" "TEST_ROLE_ID=$TEST_ROLE_ID")
    [[ -n "${GATEWAY_URL:-}" ]]     && compose_cmd+=("-e" "GATEWAY_URL=$GATEWAY_URL")
    [[ -n "${BACKEND_URL:-}" ]]     && compose_cmd+=("-e" "BACKEND_URL=$BACKEND_URL")
    [[ -n "$suites_filter" ]]       && compose_cmd+=("-e" "TEST_SUITES=$suites_filter")

    compose_cmd+=("test-runner")

    local start
    start=$(date +%s%3N)
    local exit_code=0

    "${compose_cmd[@]}" 2>&1 || exit_code=$?

    local elapsed
    elapsed=$(elapsed_since "$start")

    local label="Integration"
    [[ -n "$suites_filter" ]] && label="Integration ($suites_filter)"

    if (( exit_code == 0 )); then
        echo -e "\n  ${BOLD_GREEN}✓ Integration tests passed${RESET} $(fmt_ms $elapsed)"
        record_result "$label" "pass" "$elapsed"
    else
        echo -e "\n  ${BOLD_RED}✗ Integration tests failed${RESET} $(fmt_ms $elapsed)"
        record_result "$label" "fail" "$elapsed" "exit code $exit_code"
    fi
}

# ── Summary ───────────────────────────────────────────────────────────────────

print_summary() {
    local total_wall="$1"
    local n=${#RESULT_NAMES[@]}

    echo
    rule "Results"
    echo

    local pass_count=0 fail_count=0 skip_count=0
    local total_tests=0

    # Column widths
    local name_w=32 status_w=10 time_w=10 counts_w=24

    printf "  ${BOLD_WHITE}%-${name_w}s  %-${status_w}s  %-${time_w}s  %s${RESET}\n" \
        "Suite" "Status" "Time" "Tests"
    printf "  ${DIM}%-${name_w}s  %-${status_w}s  %-${time_w}s  %s${RESET}\n" \
        "$(printf '─%.0s' $(seq 1 $name_w))" \
        "$(printf '─%.0s' $(seq 1 $status_w))" \
        "$(printf '─%.0s' $(seq 1 $time_w))" \
        "$(printf '─%.0s' $(seq 1 $counts_w))"

    for (( i=0; i<n; i++ )); do
        local name="${RESULT_NAMES[$i]}"
        local status="${RESULT_STATUS[$i]}"
        local ms="${RESULT_TIMES[$i]}"
        local detail="${RESULT_DETAILS[$i]:-}"

        local status_str color
        case "$status" in
            pass)  color="$BOLD_GREEN"; status_str="✓ passed"; (( ++pass_count )) ;;
            fail)  color="$BOLD_RED";   status_str="✗ FAILED"; (( ++fail_count )) ;;
            skip)  color="$YELLOW";     status_str="○ skipped"; (( ++skip_count )) ;;
            error) color="$BOLD_RED";   status_str="! ERROR";   (( ++fail_count )) ;;
            *)     color="$DIM";        status_str="? unknown" ;;
        esac

        # Accumulate total test count from detail field (e.g. "242 passed")
        local suite_tests
        suite_tests=$(echo "$detail" | grep -oP '^\d+(?= passed)' | head -1 || true)
        if [[ -n "$suite_tests" ]]; then
            (( total_tests += suite_tests ))
        fi

        local time_str
        time_str=$(fmt_ms "$ms")

        # For failed suites show counts+reason; for passing show counts; for skip show reason
        local detail_str=""
        if [[ -n "$detail" ]]; then
            if [[ "$status" == "pass" ]]; then
                detail_str="${DIM}${detail}${RESET}"
            else
                detail_str="${RED}${detail}${RESET}"
            fi
        fi

        printf "  ${WHITE}%-${name_w}s${RESET}  ${color}%-${status_w}s${RESET}  ${DIM}%-${time_w}s${RESET}  " \
            "$name" "$status_str" "$time_str"
        echo -e "$detail_str"
    done

    echo
    printf "  ${DIM}%-${name_w}s  %-${status_w}s  %-${time_w}s  %s${RESET}\n" \
        "$(printf '─%.0s' $(seq 1 $name_w))" \
        "$(printf '─%.0s' $(seq 1 $status_w))" \
        "$(printf '─%.0s' $(seq 1 $time_w))" \
        "$(printf '─%.0s' $(seq 1 $counts_w))"

    local total=$(( pass_count + fail_count + skip_count ))

    if (( fail_count == 0 )); then
        local final_color="$BOLD_GREEN"
        local verdict="ALL PASSED"
    else
        local final_color="$BOLD_RED"
        local verdict="$fail_count FAILED"
    fi

    echo
    printf "  ${final_color}%-20s${RESET}" "$verdict"
    printf "  ${GREEN}%d suites passed${RESET}" "$pass_count"
    if (( fail_count > 0 ));  then printf "   ${RED}%d suites failed${RESET}"   "$fail_count";  fi
    if (( skip_count > 0 ));  then printf "   ${YELLOW}%d suites skipped${RESET}" "$skip_count"; fi
    printf "   ${DIM}%d total suites${RESET}" "$total"
    if (( total_tests > 0 )); then printf "   ${BOLD_WHITE}%d tests${RESET}" "$total_tests"; fi
    printf "   ${DIM}%s${RESET}\n" "$(fmt_ms $total_wall)"
    echo

    (( fail_count == 0 ))
}

# ── Interactive menu ──────────────────────────────────────────────────────────

show_menu() {
    echo
    rule "Select Tests to Run"
    echo
    echo -e "  ${BOLD_WHITE}Unit Tests${RESET}"
    echo -e "  ${DIM}──────────────────────────────────────${RESET}"
    echo -e "  ${CYAN}[1]${RESET}  Frontend     ${DIM}(Vitest)${RESET}"
    echo -e "  ${CYAN}[2]${RESET}  Backend      ${DIM}(pytest — unit)${RESET}"
    echo -e "  ${CYAN}[3]${RESET}  Bot          ${DIM}(pytest — unit)${RESET}"
    echo
    echo -e "  ${BOLD_WHITE}Integration Tests  ${DIM}(requires live Docker stack)${RESET}"
    echo -e "  ${DIM}──────────────────────────────────────${RESET}"
    echo -e "  ${CYAN}[4]${RESET}  All integration suites"
    echo -e "  ${DIM}──────────────────────────────────────${RESET}"
    for i in "${!SUITE_LABELS[@]}"; do
        local num=$(( i + 5 ))
        printf "  ${CYAN}[%d]${RESET}  Suite %s\n" "$num" "${SUITE_LABELS[$i]}"
    done
    echo -e "  ${DIM}──────────────────────────────────────${RESET}"
    echo -e "  ${CYAN}[a]${RESET}  All of the above"
    echo -e "  ${CYAN}[q]${RESET}  Quit"
    echo
    printf "  Enter choices (e.g. ${BOLD_WHITE}1 2 4${RESET} or ${BOLD_WHITE}a${RESET}): "
    read -r raw_input

    local selection="$raw_input"
    [[ "$selection" == "q" || "$selection" == "Q" ]] && { echo; exit 0; }
    [[ "$selection" == "a" || "$selection" == "A" ]] && selection="1 2 3 4"

    parse_and_run "$selection"
}

# ── Argument parser ────────────────────────────────────────────────────────────

parse_and_run() {
    local args="$*"
    local run_frontend=false run_backend=false run_bot=false
    local run_integration_all=false
    declare -a integration_suites=()

    for token in $args; do
        case "$token" in
            1|frontend)          run_frontend=true ;;
            2|backend)           run_backend=true ;;
            3|bot)               run_bot=true ;;
            4|integration)       run_integration_all=true ;;
            all)                 run_frontend=true; run_backend=true; run_bot=true; run_integration_all=true ;;
            integration:*)
                local filter="${token#integration:}"
                IFS=',' read -ra nums <<< "$filter"
                for num in "${nums[@]}"; do
                    integration_suites+=("$(printf '%02d' "$num")")
                done
                ;;
            [5-9]|1[0-2])
                # Menu numbers 5-12 → integration suites 01-08
                local suite_idx=$(( token - 5 ))
                integration_suites+=("$(printf '%02d' $(( suite_idx + 1 )))")
                ;;
            *)
                echo -e "  ${YELLOW}⚠ Unknown option: '$token' — ignored${RESET}"
                ;;
        esac
    done

    # Merge integration_all into suite list
    if $run_integration_all; then
        integration_suites=()  # clear specific, run all
    fi

    # Validate something was selected
    if ! $run_frontend && ! $run_backend && ! $run_bot \
       && ! $run_integration_all && [[ ${#integration_suites[@]} -eq 0 ]]; then
        echo -e "\n  ${YELLOW}Nothing selected.${RESET}"
        exit 0
    fi

    local wall_start
    wall_start=$(date +%s%3N)

    $run_frontend && run_frontend
    $run_backend  && run_backend
    $run_bot      && run_bot

    if $run_integration_all; then
        run_integration ""
    elif [[ ${#integration_suites[@]} -gt 0 ]]; then
        local joined
        joined=$(IFS=','; echo "${integration_suites[*]}")
        run_integration "$joined"
    fi

    local wall_elapsed
    wall_elapsed=$(elapsed_since "$wall_start")

    print_summary "$wall_elapsed"
}

# ── Banner ─────────────────────────────────────────────────────────────────────

print_banner() {
    echo
    echo -e "${BOLD_CYAN}  ┌─────────────────────────────────────────────────────────┐${RESET}"
    echo -e "${BOLD_CYAN}  │${BOLD_WHITE}        Baseline Framework — Test Runner                  ${BOLD_CYAN}│${RESET}"
    echo -e "${BOLD_CYAN}  └─────────────────────────────────────────────────────────┘${RESET}"
    echo
    # Load .env.test.local early so banner reflects its values
    local env_file="$SCRIPT_DIR/.env.test.local"
    [[ -f "$env_file" ]] && { set -a; source "$env_file"; set +a; }

    [[ -n "${TEST_API_TOKEN:-}" ]] \
        && echo -e "  ${DIM}Token:${RESET}   ${GREEN}provided (authenticated tests enabled)${RESET}" \
        || echo -e "  ${DIM}Token:${RESET}   ${YELLOW}not set — L2+ tests will be skipped  (add to .env.test.local)${RESET}"
    [[ -n "${TEST_GUILD_ID:-}" ]] \
        && echo -e "  ${DIM}Guild:${RESET}   ${GREEN}${TEST_GUILD_ID}${RESET}" \
        || echo -e "  ${DIM}Guild:${RESET}   ${YELLOW}not set — guild-scoped tests will be skipped${RESET}"
    [[ -n "${TEST_USER_ID:-}" ]]  && echo -e "  ${DIM}User:${RESET}    ${GREEN}${TEST_USER_ID}${RESET}"
    [[ -n "${TEST_ROLE_ID:-}" ]]  && echo -e "  ${DIM}Role:${RESET}    ${GREEN}${TEST_ROLE_ID}${RESET}"
    echo -e "  ${DIM}Gateway:${RESET} ${CYAN}${GATEWAY_URL:-http://localhost}${RESET}"
    echo
}

# ── Entry point ────────────────────────────────────────────────────────────────

print_banner

if [[ $# -eq 0 ]]; then
    show_menu
else
    parse_and_run "$@"
fi
