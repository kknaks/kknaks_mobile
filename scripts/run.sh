#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."

LOG_DIR="logs"
BRIDGE_PID_FILE="$LOG_DIR/bridge.pid"
WORKER_PID_FILE="$LOG_DIR/worker.pid"
BRIDGE_LOG="$LOG_DIR/bridge.log"
WORKER_LOG="$LOG_DIR/worker.log"

if command -v caffeinate >/dev/null 2>&1; then
  CAFFEINATE="caffeinate -i"
else
  CAFFEINATE=""
fi

show_help() {
  cat <<'EOF'
kknaks_mobile — Slack <-> Claude Code bridge runner

Commands:
  up                          redis + bridge + worker 시작 (detached, caffeinate 포함)
  down                        전부 종료 + redis 컨테이너 내림
  restart                     down 후 up
  status                      프로세스/컨테이너 상태 확인
  logs [bridge|worker|both]   로그 tail (기본: both)
  help                        이 도움말

실행 전 체크리스트:
  1. .env 작성 완료
       - SLACK_BOT_TOKEN / SLACK_APP_TOKEN / SLACK_SIGNING_SECRET
       - WORK_DIR (프로젝트들이 있는 상위 디렉토리)
       - REDIS_URL은 redis://127.0.0.1:36379 (host port 36379)
  2. Docker Desktop 실행 중
  3. uv 설치됨 (/Users/kknaks/.local/bin/uv)

로그 위치:
  logs/bridge.log   Slack bridge
  logs/worker.log   Queue worker
  logs/*.pid        프로세스 추적 (down 시 자동 삭제)

⚠️  절전 모드 주의 (macOS):
  - 'caffeinate -i' 로 유휴(idle) 절전은 막아둠
  - 그러나 노트북 뚜껑을 닫으면 아래 조건 전부 만족해야 clamshell 모드 유지:
      (1) 전원 어댑터 연결
      (2) 외부 디스플레이 켜져 있고 신호 들어옴
      (3) 외부 키보드/마우스 연결
  - 모니터 전원을 끄면 macOS가 디스플레이 끊겼다고 판단 → 시스템 잠듦
  - macOS가 잠들면 Docker VM(및 모든 컨테이너)도 같이 멈춤
  - 24h 운영 시: HDMI/DP 더미 플러그 또는 모니터 ON 유지 권장
  - 과격하지만 확실한 방법: sudo pmset -a disablesleep 1 (되돌리기: ... 0)

사용 예:
  ./scripts/run.sh up
  ./scripts/run.sh status
  ./scripts/run.sh logs worker
  ./scripts/run.sh down
EOF
}

is_running() {
  local pid_file="$1"
  [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null
}

kill_tree() {
  local pid="$1"
  local sig="${2:-TERM}"
  local children
  children=$(pgrep -P "$pid" 2>/dev/null || true)
  for child in $children; do
    kill_tree "$child" "$sig"
  done
  kill -"$sig" "$pid" 2>/dev/null || true
}

start_process() {
  local name="$1"
  local script="$2"
  local log_file="$3"
  local pid_file="$4"

  if is_running "$pid_file"; then
    echo "[$name] already running (PID $(cat "$pid_file"))"
    return
  fi

  nohup $CAFFEINATE ./scripts/"$script" >> "$log_file" 2>&1 &
  echo $! > "$pid_file"
  echo "[$name] started (PID $!) -> $log_file"
}

stop_process() {
  local name="$1"
  local pid_file="$2"

  if [[ ! -f "$pid_file" ]]; then
    echo "[$name] not running (no pid file)"
    return
  fi

  local pid
  pid=$(cat "$pid_file")
  if kill -0 "$pid" 2>/dev/null; then
    kill_tree "$pid" TERM
    for _ in 1 2 3 4 5; do
      kill -0 "$pid" 2>/dev/null || break
      sleep 1
    done
    if kill -0 "$pid" 2>/dev/null; then
      kill_tree "$pid" KILL
    fi
    echo "[$name] stopped (PID $pid)"
  else
    echo "[$name] was not running"
  fi
  rm -f "$pid_file"
}

cmd="${1:-help}"

case "$cmd" in
  up)
    mkdir -p "$LOG_DIR"
    ./scripts/redis.sh up
    start_process "bridge" "run_bridge.sh" "$BRIDGE_LOG" "$BRIDGE_PID_FILE"
    start_process "worker" "run_worker.sh" "$WORKER_LOG" "$WORKER_PID_FILE"
    echo ""
    echo "Detached. 터미널 닫아도 살아있음."
    echo "  logs:   ./scripts/run.sh logs [bridge|worker|both]"
    echo "  status: ./scripts/run.sh status"
    echo "  stop:   ./scripts/run.sh down"
    echo ""
    echo "※ 노트북 뚜껑 닫고 모니터 끄면 macOS가 잠들어 Docker까지 멈춥니다."
    echo "  자세한 설명: ./scripts/run.sh help"
    ;;
  down)
    stop_process "bridge" "$BRIDGE_PID_FILE"
    stop_process "worker" "$WORKER_PID_FILE"
    ./scripts/redis.sh down || true
    ;;
  restart)
    "$0" down || true
    "$0" up
    ;;
  status)
    if is_running "$BRIDGE_PID_FILE"; then
      echo "bridge: running (PID $(cat "$BRIDGE_PID_FILE"))"
    else
      echo "bridge: stopped"
    fi
    if is_running "$WORKER_PID_FILE"; then
      echo "worker: running (PID $(cat "$WORKER_PID_FILE"))"
    else
      echo "worker: stopped"
    fi
    ./scripts/redis.sh status
    ;;
  logs)
    target="${2:-both}"
    case "$target" in
      bridge) tail -f "$BRIDGE_LOG" ;;
      worker) tail -f "$WORKER_LOG" ;;
      both)   tail -f "$BRIDGE_LOG" "$WORKER_LOG" ;;
      *) echo "Usage: $0 logs [bridge|worker|both]"; exit 1 ;;
    esac
    ;;
  help|-h|--help)
    show_help
    ;;
  *)
    echo "Unknown command: $cmd"
    echo ""
    show_help
    exit 1
    ;;
esac
