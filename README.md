# kknaks-mobile

로컬 머신에서 돌아가는 **Claude Code를 Slack에서 원격 조작**하는 브리지.
폰에서 Slack 봇에 DM / 채널 멘션으로 지시하면, 로컬 Claude Code가 작업하고 결과를 실시간 스트리밍으로 되돌려준다.

- 이미지 첨부해서 질문 → Claude가 분석해서 답변
- "README 보내줘" 같은 요청 → 로컬 파일을 Slack에 업로드
- 스레드/DM별 세션 유지, 대화 이어가기
- `!clear` / `!resume` / `!help` 명령어

## 아키텍처

```
┌──────────────────┐  Socket Mode (WebSocket)
│  Slack (폰/PC)   │ ◀──────────────────────────┐
└──────────────────┘                            │
                                                │
┌───────────────────────────────────────────────┼──────┐
│  Mac 로컬                                     │      │
│                                               ▼      │
│  ┌────────────┐    ┌──────────────┐    ┌─────────┐   │
│  │  Redis     │◀──▶│ open-kknaks  │    │ Bridge  │   │
│  │  (docker)  │    │   Worker     │    │ (Slack  │   │
│  │            │    │              │    │  Bolt)  │   │
│  └────────────┘    └──────┬───────┘    └─────────┘   │
│                           │ PTY                      │
│                           ▼                          │
│                    claude -p ...                     │
└──────────────────────────────────────────────────────┘
```

- **Redis**: [open-kknaks](https://pypi.org/project/open-kknaks/) 태스크 큐 브로커 + 세션/메타 저장
- **Worker**: open-kknaks가 Claude Code CLI를 PTY로 실행, 결과를 Redis 스트림에 publish
- **Bridge**: Slack Bolt(Socket Mode) 앱. 이벤트 수신 → 태스크 제출 → 스트림 이벤트를 Slack 메시지에 실시간 업데이트

## 요구사항

- **macOS / Linux** (Windows 미지원 — open-kknaks가 POSIX PTY 사용)
- **Docker + Docker Compose**
- **Node.js 20+** (Claude Code CLI)
- **Python 3.12+** (uv가 자동 관리)
- **Claude Code CLI** 설치 + 로그인 완료

## 설치

### 1. Claude Code CLI

```bash
npm install -g @anthropic-ai/claude-code
claude login
```

`which claude && claude --version` 으로 확인.

### 2. uv (Python 패키지 매니저)

이미 있으면 건너뛰기:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```
설치 후 새 쉘 열거나 `source ~/.zshrc`.

### 3. 리포 클론 + 의존성

```bash
git clone <repo-url>
cd kknaks_mobile
uv sync      # .venv 자동 생성 + 의존성 설치
```

### 4. Slack 앱 생성

https://api.slack.com/apps → **Create New App** → **From a manifest**

워크스페이스 선택 → 아래 YAML 붙여넣기 → Create:

```yaml
display_information:
  name: kknaks-mobile
  description: 원격 Claude Code 브리지
  background_color: "#1a1a1a"
features:
  bot_user:
    display_name: kknaks-mobile
    always_online: true
oauth_config:
  scopes:
    bot:
      - app_mentions:read
      - chat:write
      - chat:write.public
      - im:history
      - im:read
      - im:write
      - files:read
      - files:write
      - channels:history
      - groups:history
      - reactions:write
      - assistant:write
settings:
  event_subscriptions:
    bot_events:
      - app_mention
      - message.im
      - message.channels
      - message.groups
  interactivity:
    is_enabled: true
  socket_mode_enabled: true
  token_rotation_enabled: false
```

만든 뒤:

1. **Basic Information → App-Level Tokens → Generate Token and Scopes**
   - Name: 아무거나 / Scope: `connections:write` → **Generate**
   - `xapp-...` 토큰 복사 (닫으면 못 봄, 주의)
2. **OAuth & Permissions → Install to Workspace** → 허용
   - 상단 **Bot User OAuth Token** (`xoxb-...`) 복사
3. **Basic Information → App Credentials → Signing Secret** 복사
4. **App Home → Show Tabs → Messages Tab 체크** + 바로 아래 **"Allow users to send Slash commands and messages from the messages tab"** 체크
5. (선택) 채널에서 쓰려면 `/invite @kknaks-mobile`

### 5. `.env` 작성

```bash
cp .env.example .env
```

```ini
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
SLACK_SIGNING_SECRET=...

REDIS_URL=redis://127.0.0.1:6379
REDIS_NAMESPACE=kknaks_mobile

WORK_DIR=/path/to/your/projects
UPLOAD_DIR=${WORK_DIR}/.kknaks_mobile_uploads
```

**중요:**
- `WORK_DIR` — Claude가 파일을 읽고 쓸 루트 디렉토리 (본인 프로젝트 부모 경로)
- `UPLOAD_DIR` — Slack에서 첨부된 이미지가 임시 저장되는 경로. **반드시 `WORK_DIR` 안**으로 둘 것 (그렇지 않으면 Claude가 Read 권한 없음)
- `REDIS_URL`은 `127.0.0.1`로 (macOS에서 `localhost`는 IPv6으로 해석되는데 Docker Redis는 IPv4만 바인딩)

## 실행

**터미널 3개** (또는 `tmux` / iTerm 탭):

```bash
# 1. Redis
./scripts/redis.sh up

# 2. Worker  (open-kknaks가 claude -p를 PTY로 실행)
./scripts/run_worker.sh

# 3. Bridge  (Slack ↔ open-kknaks 어댑터)
./scripts/run_bridge.sh
```

Bridge 로그에 `⚡️ Bolt app is running!` 뜨면 준비 완료.

## 사용법

### 기본 대화

**DM**: 봇 DM 창에서 그냥 메시지 → 답장.
**채널**: `@kknaks-mobile <질문>` → 스레드로 답장. 이후 같은 스레드 내 답장은 **멘션 없이도** 이어감.

### 파일 첨부 (수신)

이미지/파일을 Slack에 첨부 + 질문:
> 📷 screenshot.png + "이 에러 뭐가 문제야?"

Bridge가 파일을 `UPLOAD_DIR`에 저장 → Claude가 Read 도구로 분석 → 답변. 처리 끝나면 파일 삭제.

지원 타입: 이미지(png/jpg/gif/webp), PDF, 텍스트/코드 등 Claude Read가 인식하는 모든 것.

### 파일 받기 (송신)

> "paper_kknaks README 보내줘"

Claude가 응답에 `<send-file>/절대/경로</send-file>` 태그 포함 → Bridge가 파싱해서 `files_upload_v2`로 Slack 스레드에 업로드. 태그는 표시 메시지에서 제거됨.

### 명령어

`!` 접두어 사용. (Slack이 `/`로 시작하는 메시지를 슬래시 명령으로 가로채서 봇까지 안 옴.)

| 명령 | 동작 |
|---|---|
| `!help` | 도움말 |
| `!clear` | 현재 스레드 / DM 세션 리셋 |
| `!resume` | 이 채널의 최근 세션 목록 (thread_key, session_id 앞자리, 첫 프롬프트 프리뷰) |

## 세션 동작

- **채널 스레드**: 각 스레드 = 독립 세션. 스레드 루트 ts를 키로 사용.
- **DM (top-level)**: 한 DM 채널 전체가 한 세션(`thread_key="main"`) — 긴 메신저 대화 UX. 리셋은 `!clear`.
- **DM (스레드 답장)**: 해당 스레드만의 별개 세션.

세션 데이터는 Redis에 7일 TTL로 저장. thread_key ↔ session_id 매핑 + 첫 프롬프트 프리뷰 + last_seen timestamp.

## 디렉토리 구조

```
kknaks_mobile/
├── docker-compose.yml       # Redis 서비스
├── pyproject.toml / uv.lock # uv 프로젝트
├── .env / .env.example
├── src/
│   ├── main.py              # 진입점: broker/client/sessions 초기화 + Bolt 기동
│   └── bridge/
│       ├── app.py           # Slack Bolt 이벤트 핸들러 (mention/message)
│       ├── runner.py        # ClaudeClient 제출 + 스트림 → chat.update
│       ├── commands.py      # !명령어
│       ├── sessions.py      # Redis 세션/메타/인덱스
│       └── files.py         # Slack 파일 다운로드 + <send-file> 파싱
└── scripts/
    ├── redis.sh             # docker compose 래퍼 (up/down/cli/...)
    ├── run_worker.sh        # open-kknaks 워커 실행
    ├── run_bridge.sh        # Slack 브리지 실행
    └── smoke.py             # 독립 검증 (태스크 하나 제출 → 결과 확인)
```

## 문제 해결

**Redis 포트 충돌 (`port is already allocated`)**
- 다른 Redis 컨테이너가 6379를 쓰고 있음. `docker ps`로 확인 후 끄거나 `docker-compose.yml`의 포트 바꾸기.

**Worker가 `Connection refused`**
- `REDIS_URL=redis://localhost:...`이면 IPv6 문제. `redis://127.0.0.1:...`로 바꾸기.

**이미지 첨부 시 Claude가 권한 승인 요청**
- `UPLOAD_DIR`이 `WORK_DIR` 밖이라서 Claude가 Read 못 함. `WORK_DIR` 하위 경로로 수정 후 재시작.

**채널 스레드에서 멘션 없이는 반응 없음**
- `channels:history` 스코프 + `message.channels` 이벤트 구독이 되어 있는지 확인 후 앱 재설치.

**같은 답변이 두 번 온다**
- 구버전 코드 문제. 최신 코드에선 `delta_buffer` 비교로 중복 제거됨.

## 메모

- **open-kknaks 1.1.0 관련 우회**:
  - `--include-partial-messages` 플래그가 하드코딩되어 있어 `text` 이벤트가 delta + finalized 두 경로로 중복 발행됨. Bridge에서 `delta_buffer` 매칭으로 중복 건너뜀.
  - `--add-dir`가 가변 인자(`<directories...>`)라 플래그 직후에 온 프롬프트까지 디렉토리로 먹음. `UPLOAD_DIR`을 `WORK_DIR` 안에 두고 `--add-dir`를 아예 안 씀.

## 라이선스

MIT
