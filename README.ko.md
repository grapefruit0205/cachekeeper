# cachekeeper

**살아 있는 프롬프트 캐시를 실수로 버리지 않게 해 주는 Claude Code 플러그인입니다.** 두 가지로 이루어져 있습니다.

- **모델 전환 가드**: `/model`이나 모델 선택기로 캐시가 살아 있는 세션의 모델을 바꾸려 하면, 잃게 될 양과 캐시를 지키는 대안을 보여 주고 먼저 묻습니다.
- **`cachekeeper audit`**: 내 대화 기록을 읽어 캐시 재구축을 원인별로 나눠, 어떤 습관이 가장 비싼지 보여 줍니다.

[English](README.md)

## 왜 필요한가

Claude Code는 매 턴마다 대화 전체를 다시 보냅니다. 프롬프트 캐시 덕분에 이게 싸게 처리됩니다(캐시 읽기는 입력 가격의 약 0.1배). 캐시를 다시 만들면 맥락 전체를 다시 씁니다. 구독 요금제의 1시간 TTL에서는 입력 가격의 2배입니다. 만든 사람의 최근 30일(메인 세션 131개, 요청 8,664개)을 API 정가로 환산하면 이렇습니다.

| | 전체 사용량 대비 |
|---|---|
| 캐시 읽기 | 55.2% |
| 캐시 쓰기 | 31.7% |
| 출력 | 13.1% |

캐시 쓰기의 원인이 된 재구축은 이렇게 나뉩니다.

| 원인 | 재구축 횟수 | 중간 크기 | 전체 사용량 대비 |
|---|---|---|---|
| **모델 전환 (`/model`)** | 35 | 54.5만 토큰 | **8.1%** |
| **1시간 넘게 쉼 (TTL 만료)** | 39 | 47.0만 토큰 | **7.3%** |
| 기타 (도구 정의, 업그레이드, 이미지) | 16 | 63.5만 토큰 | 3.1% |
| 세션 시작·재개 | 18 | 14.7만 토큰 | 2.7% |
| 자동 전환, effort 변경, 압축 | 13 | | 1.5% |

45만 토큰짜리 세션에서 Opus 5와 Fable 5.1 사이를 한 번 오가면 대화 전체를 새 모델에 다시 캐싱합니다(Fable 5.1 정가로 약 $9). 전체 기록은 [docs/measurement-2026-09-23.md](docs/measurement-2026-09-23.md)에 있습니다.

## 모델 전환 가드

전환 비용은 Claude Code가 이미 계산합니다. `PreModelSwitch` hook 입력에 `prompt_cache_warm`, `context_tokens`, `cache_ttl`, `estimated_cache_write_usd`가 들어 있습니다(Claude Code 2.1.280에서 확인). 캐시가 살아 있고 다시 쓰는 비용이 `$1` 이상이면 cachekeeper가 `ask`로 이렇게 답합니다.

```
cachekeeper: opus-5 → fable-5-1로 바꾸면 지금 살아 있는 캐시(1h)를 버리고 대화 452k 토큰을
fable-5-1에 다시 씁니다 — 약 $9.04 (API 정가 기준). 이 작업에만 fable-5-1가 필요하면 전환 대신
"이 부분은 fable 서브에이전트로 처리해줘"라고 맡기면 메인 세션의 캐시가 유지됩니다.
그래도 바꾸려면 120초 안에 같은 모델을 다시 선택하세요.
```

- 터미널 세션에서는 Claude Code가 이 문구로 확인 창을 띄웁니다.
- 확인 창을 띄울 수 없는 세션(headless `-p`, 그리고 다른 클라이언트도 그럴 수 있음)에서는 전환이 이 문구와 함께 막히고, **120초 안에 같은 전환을 다시 요청하면 그게 확인입니다.** 실제로 확인했습니다. 첫 `/model sonnet`은 문구와 함께 막혔고, 두 번째는 통과했습니다(`Set model to Sonnet 5`).
- 캐시가 이미 식은 전환, 맥락이 작은 전환, 자동 폴백, 세션 재개 때의 모델 복원은 조용히 통과합니다. `PreModelSwitch`는 `/model`, 모델 선택기, SDK 호출에서만 실행됩니다.
- 서브에이전트는 메인 캐시를 건드리지 않습니다. 호출과 결과가 대화 끝에 붙을 뿐이고, 서브에이전트는 자기 모델로 자기 캐시를 따로 만듭니다.

모든 전환 요청과 실제 전환은 플러그인 데이터 디렉터리의 `events.jsonl`에 기록됩니다. 모델 이름, 토큰 수, 추정 비용, 결정만 남고 프롬프트 내용은 남지 않습니다. `cachekeeper events`로 요약해 볼 수 있습니다.

## 감사(audit)

```
cachekeeper audit            # 최근 30일, 로케일 언어(ko/en)로
cachekeeper audit --days 7 --json
```

세션 안에서는 `/cachekeeper:audit`로 실행할 수 있습니다. `~/.claude/projects/*/*.jsonl`(메인 세션만, 서브에이전트 제외)을 읽고, 세션 재개로 다른 파일에 복사된 응답도 한 번만 셉니다. 보고하는 내용은 네 가지입니다.

- 사용량 구성: 캐시 읽기, 캐시 쓰기, 출력, 입력
- 모든 재구축과 그 원인: 세션 시작, 직접 또는 자동 모델 전환, effort 변경, 압축, TTL 만료, 기타
- 가드 재현: 내 전환 중 가드가 물었을 횟수와, 그 답에 걸려 있던 사용량
- 55분 keep-alive 재현: 핑 비용과, 그 핑이 막았을 만료 재구축

비중은 API 정가로 환산한 값입니다. 구독 요금제가 사용량을 어떻게 세는지는 공개되어 있지 않으니, 청구액이 아니라 "사용량의 어느 부분인가"로 읽어 주세요.

## keep-alive는 일부러 넣지 않았습니다

쉬는 동안 캐시를 살려 두는 프로젝트가 이미 여럿 있고, 방식도 각각 다릅니다. 먼저 감사를 돌려 보세요. keep-alive 줄이 내 기록에서 핑 값이 빠졌을지 알려 줍니다. 만든 사람 기록에서는 핑이 사용량의 2.2%, 막은 재구축이 4.5%로 순효과 +2.3%였습니다.

| 프로젝트 | 방식 |
|---|---|
| [Delitefully/claude-keepwarm](https://github.com/Delitefully/claude-keepwarm) | 45분 동안 입력이 없으면 "마침표 하나"를 요청하는 한 줄을 보내고, 남은 줄을 숨김 |
| [FiredMosquito831/claude-cache-warm](https://github.com/FiredMosquito831/claude-cache-warm) | 상태 표시줄, 대시보드, 세션별 설정이 있는 플러그인 |
| [santiquiroz/claude-prompt-cache-keepalive](https://github.com/santiquiroz/claude-prompt-cache-keepalive) | 백그라운드 타이머들이 세션을 깨움. 반복 `CronCreate` 작업은 쉬는 세션에서 한 번도 실행되지 않았고, `ScheduleWakeup`은 `/loop` 안에서만 동작했다는 실측 포함 |
| [Pan1127/cc-cache-keepalive](https://github.com/Pan1127/cc-cache-keepalive) | 저장되지 않는 복제 세션에서 핑을 보내 원래 세션에 메시지가 쌓이지 않음 |
| [cnighswonger/claude-code-coffee](https://github.com/cnighswonger/claude-code-coffee) | 쉬기 전에 `/coffee 30` |

Claude Code 자체 기능도 있습니다. 상태 표시줄에 캐시 만료 시각이 전달되고, `/usage`가 적중률과 마지막 캐시 미스의 원인을 보여 주며, 오래 쉰 큰 세션을 재개하면 요약에서 이어 가기를 제안합니다.

## 설치

```
claude plugin marketplace add grapefruit0205/cachekeeper
claude plugin install cachekeeper@cachekeeper
```

Python 3.8 이상이 필요합니다. 없으면 hook이 아무 말 없이 모든 전환을 통과시킵니다. `PreModelSwitch` hook을 지원하는 Claude Code도 필요합니다. 체크아웃한 폴더로 바로 시험하려면 `claude --plugin-dir /path/to/cachekeeper`를 쓰세요.

| 변수 | 기본값 | 효과 |
|---|---|---|
| `CACHEKEEPER_MODE` | `ask` | `ask`, `warn`(막지 않고 문구만 표시), `off` |
| `CACHEKEEPER_MIN_USD` | `1.0` | 다시 쓰는 추정 비용이 이 이상일 때만 묻기 |
| `CACHEKEEPER_MIN_TOKENS` | `100000` | 새 모델 가격을 모를 때 쓰는 기준 |
| `CACHEKEEPER_CONFIRM_SECONDS` | `120` | 다시 요청을 확인으로 인정하는 시간 |
| `CACHEKEEPER_LANG` | `LANG`에서 | `ko` 또는 `en` |

`~/.claude/settings.json`의 `env` 항목에 넣으면 됩니다.

## 한계

- `prompt_cache_warm`은 지금 모델의 캐시만 가리킵니다. TTL 안에 썼던 모델로 되돌아가면 그 모델의 캐시가 맞을 수 있어서, 실제 재구축은 물어본 것보다 작을 수 있습니다. 재현에서는 29번 물은 것 중 25번이 실제 재구축으로 이어졌습니다.
- 두 재현은 가드와 keep-alive가 했을 일을 모사한 것입니다. 실제로 얼마를 아끼는지는 사용자의 답과 쉬는 습관에 달려 있습니다.
- 가드는 Claude Code가 `PreModelSwitch`로 넘기는 전환만 봅니다. effort 변경도 대부분의 모델에서 캐시를 무효화합니다(Opus 5.5와 Fable 5.1은 예외). 이 경우는 캐시가 살아 있을 때 Claude Code가 직접 확인을 묻습니다.

## 테스트

```
python3 -m unittest discover -s tests
```

MIT 라이선스.
