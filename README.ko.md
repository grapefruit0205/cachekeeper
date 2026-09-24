<p align="center"><img src="assets/icon.png" width="160" alt="cachekeeper icon: a shield around a stack of cache layers with a refresh arrow"></p>

# cachekeeper

[English](README.md) · **한국어**

**살아 있는 프롬프트 캐시를 실수로 버리지 않게 해 주는 Claude Code 플러그인입니다.** 다음 세 가지 핵심 기능으로 구성되어 있습니다.

- 🛡️ **모델 전환 가드**: `/model`이나 모델 선택기로 캐시가 살아 있는 세션의 모델을 바꾸려 할 때, 손실될 사용량과 캐시를 지키는 대안을 먼저 안내하고 확인을 구합니다.
- ⚡ **스마트 Keep-Alive (기본 활성화)**: 자리를 비운 동안 55분마다 짧은 핑을 보내 긴 세션의 캐시를 살려 둡니다. 사용자의 실제 사용 기록상 다시 구축하는 것보다 비용이 저렴한 기간까지만 유지합니다.
- 📊 **대화 감사 (`cachekeeper audit`)**: 내 대화 기록으로 Keep-Alive와 가드가 사용량을 몇 % 줄이는지(절감률) 보여 줍니다. 캐시 재구축도 원인별로 나눠, 어떤 사용 습관이 가장 큰 비용을 발생시키는지 보여 줍니다.

---

## 목차
- [설치](#설치)
  - [Windows에서 사용하려면](#windows에서-사용하려면)
- [사용법](#사용법)
- [기대 효과](#기대-효과)
- [Q&A](#qa)
- [왜 필요한가](#왜-필요한가)
- [두 가지 잣대 (과금 기준)](#두-가지-잣대)
- [모델 전환 가드 상세](#모델-전환-가드)
- [감사 (Audit)](#감사audit)
- [세션을 얼마나 키울 것인가 (자동 압축)](#세션을-얼마나-키울-것인가)
- [Keep-Alive 상세](#keep-alive)
- [요구 사항과 설정](#요구-사항과-설정)
- [한계](#한계)
- [테스트 및 라이선스](#테스트)

---

## 설치

> [!NOTE]
> Claude Code(v2.1.280 이상에 cachekeeper가 사용하는 모든 Hook이 포함되어 있습니다)와 Python 3.8 이상이 필요합니다([Windows에서 사용하려면](#windows에서-사용하려면)).

### 터미널에서 설치
```bash
claude plugin marketplace add grapefruit0205/cachekeeper
claude plugin install cachekeeper@cachekeeper
```

### Claude Code 내부에서 설치
```text
/plugin marketplace add grapefruit0205/cachekeeper
/plugin install cachekeeper@cachekeeper
```

별도의 설정 없이 즉시 동작합니다.
- **데스크톱 앱**: 현재 열려 있는 세션에도 즉시 적용됩니다.
- **터미널 세션**: 터미널을 다시 시작해야 적용됩니다.

### 업데이트 및 삭제
- **업데이트**: `claude plugin marketplace update cachekeeper` 실행 후 `claude plugin update cachekeeper@cachekeeper`
- **삭제**: `claude plugin uninstall cachekeeper@cachekeeper`

### Windows에서 사용하려면

Claude Code는 Windows에서 플러그인 Hook을 **Git Bash**로 실행하고, Git Bash가 없으면 **PowerShell**로 실행합니다. cachekeeper의 Hook은 0.9.0부터 둘 다에서 실행됩니다. Claude 데스크톱 앱과 터미널의 Claude Code 모두 같습니다. 필요한 것은 Python입니다.

1. **Python 3.8 이상 설치**: [python.org](https://www.python.org/downloads/windows/)에서 설치합니다. PowerShell에서 `python3 --version`, `python --version`, `py -3 --version` 중 하나가 3.8 이상을 출력하면 됩니다. Windows에 기본으로 들어 있는 `python`은 Microsoft Store로 안내하는 바로가기일 뿐 Python이 아닙니다.
2. **Claude 데스크톱 앱이나 터미널을 완전히 종료했다가 다시 엽니다** (데스크톱 앱은 트레이 아이콘에서도 종료). 이미 실행 중인 Claude Code는 설치 전의 환경을 그대로 쓰기 때문입니다.
3. **확인**: 새 세션에서 `/cachekeeper:audit`를 실행합니다. 리포트가 나오면 Python을 찾은 것이고, Hook도 같은 Python으로 실행됩니다. `Python 3.8 or newer is required`가 나오면 1번을 다시 확인하세요. Python이 없으면 Hook은 오류 없이 조용히 꺼져 있으므로 이 확인이 필요합니다.

Git for Windows는 없어도 됩니다. 설치되어 있으면 Claude Code가 그 Git Bash로 Hook을 실행하며, `C:\Program Files\Git`이나 PATH에 있는 `git` 옆에서 찾습니다. 다른 곳에 설치했다면 `~/.claude/settings.json`에 경로를 적습니다.

```json
{
  "env": {
    "CLAUDE_CODE_GIT_BASH_PATH": "C:\\Program Files\\Git\\bin\\bash.exe"
  }
}
```

Git Bash가 없으면 PowerShell 7(`pwsh`)이 설치되어 있으면 그것으로, 아니면 Windows에 기본으로 들어 있는 Windows PowerShell 5.1로 실행됩니다. 이때 `/cachekeeper:audit`는 `bin/cachekeeper.ps1`을 경로로 직접 실행합니다. Claude Code는 플러그인의 `bin/`을 Bash 도구의 PATH에만 넣기 때문입니다.

- **WSL**: WSL에서 실행하는 Claude Code(데스크톱 앱의 WSL 환경 포함)는 Linux와 같습니다. cachekeeper를 WSL 안의 Claude Code에 설치하면 됩니다. Python은 WSL의 Ubuntu에 기본으로 들어 있습니다.
- 제작자는 Ubuntu에서 사용합니다. Windows는 CI(GitHub의 Windows 러너에서 Git Bash, PowerShell 7, Windows PowerShell 5.1)로 테스트했고, Claude Code가 설치된 실제 Windows 기기에서는 아직 확인하지 못했습니다.

> [!NOTE]
> MSIX 패키지로 설치된 Windows 데스크톱 앱에는, 앱이 자기 폴더(`%APPDATA%\Claude`)에 풀어 둔 플러그인 파일을 Git Bash나 Python 같은 외부 프로그램이 보지 못하는 버그가 있습니다([anthropics/claude-code#96087](https://github.com/anthropics/claude-code/issues/96087)). 마켓플레이스에서 설치한 cachekeeper는 보통 `C:\Users\<이름>\.claude\plugins`에 들어가므로 해당되지 않을 것으로 보지만, 확인하지는 못했습니다. 해당되더라도 Hook은 파일을 찾지 못하면 조용히 끝나므로(Hook은 Keep-Alive 핑일 때만 exit 2를 냅니다) 무한 반복은 생기지 않고, 가드와 Keep-Alive가 동작하지 않을 뿐입니다.

---

## 사용법

평소에는 별도로 명령어를 실행할 필요 없이 세 가지 기능이 자동으로 동작합니다.

### 1. 모델을 변경할 때 (가드 동작)
`/model` 명령어나 모델 선택기로 변경을 시도할 때, 살아 있는 캐시를 버리게 되고 재구축 비용이 **$1 이상**이라면 전환을 일시 중단하고 예상 손실 금액을 표시합니다. 이후 다음 두 가지 중 하나를 선택할 수 있습니다.

1. **이 작업만 새 모델에 맡기기**: 다른 모델에 시키려던 요청을 그대로 메시지로 전송하세요. 해당 모델의 서브에이전트에 맡길지 먼저 묻습니다. 맡기면 서브에이전트가 그 요청 하나만 처리하고, 대화는 메인 세션의 모델과 살아 있는 캐시로 이어집니다. 맡기지 않으면 메인 모델이 평소처럼 답합니다.
2. **세션 모델 완전히 변경하기**: 안내문에 표시된 `/model` 명령어를 120초 안에 다시 입력하세요 (터미널 세션에서는 확인 창이 표시됩니다).

### 2. 자리를 비울 때 (Keep-Alive 동작)
긴 세션에서 마지막 메시지 전송 후 **55분**이 지나면 모델에게 짧은 핑을 보내고, 모델은 `(keep-alive)`라고만 답합니다. 이를 통해 캐시 수명이 1시간 더 연장됩니다.

- 세션별 유지 시간 한도는 사용자의 실제 복귀 기록을 기반으로 매일 재계산됩니다.
- 사용 기록상 핑을 보내는 것이 이득이 없다고 판단되면 자동으로 꺼집니다.
- 완전히 끄려면 `~/.claude/settings.json`의 `env` 객체에 아래 설정을 추가합니다:
  ```json
  {
    "env": {
      "CACHEKEEPER_KEEPALIVE": "0"
    }
  }
  ```
- 터미널에서는 상태 표시줄에 캐시 남은 시간과 다음 핑까지 남은 시간을 띄울 수 있습니다 ([설정 방법](#터미널-상태-표시줄)).

### 3. 절감률 확인 및 사용량 분석
세션 내부에서 `/cachekeeper:audit`을 입력하거나, Claude에게 아래 명령을 실행하도록 요청하세요 (플러그인이 `cachekeeper` CLI를 PATH에 등록합니다).

| 명령 | 기능 설명 |
|---|---|
| `cachekeeper audit` | Keep-Alive와 가드의 절감률, 전체 사용량 구성, 캐시 재구축 원인별 분석 |
| `cachekeeper keepalive` | 사용 기록상 가장 이득인 Keep-Alive 정책 및 현재 정책 표시 |
| `cachekeeper compaction` | 자동 압축을 더 일찍 실행했을 때의 예상 절감액 및 비용 시뮬레이션 |
| `cachekeeper events` | 가드가 개입한 모델 전환 및 Keep-Alive 핑 발송 로그 조회 |

- **옵션**:
  - `--days N`: 분석 기간 설정 (기본값: `30`일)
  - `--lang ko` / `--lang en`: 출력 언어 설정
  - `--basis subscription` / `--basis api`: 비용 계산 [잣대](#두-가지-잣대) 선택
  - `--json`: 분석 결과를 JSON 형식으로 출력
- 명령은 로컬 컴퓨터의 대화 기록만 읽으며 외부로 데이터를 전송하지 않습니다.
- **Claude Code 외부 터미널에서 실행 시**:
  ```bash
  git clone https://github.com/grapefruit0205/cachekeeper
  cachekeeper/bin/cachekeeper audit
  ```

---

## 기대 효과

구독 요금제에서는 캐시 읽기 비용이 거의 0으로 계산되므로, **대화 전체를 다시 쓰는 '재구축'이 한 턴에서 발생할 수 있는 가장 비싼 작업**입니다.

제작자의 13일간 기록(2026-09-11 ~ 09-24, 세션 178개, 구독 사용량 기준) 분석 결과:
- 모델 전환 직후 재구축: 전체 사용량의 **11.9%**
- 1시간 초과 휴식 후 재구축: 전체 사용량의 **11.5%**

해당 기록을 재현한 기능별 기대 효과는 다음과 같습니다:

| 기능 | 실제 재현 결과 (제작자 기록 기준) |
|---|---|
| **Keep-Alive** | 실제 PC 가동 시간 기준(야간 절전/종료 포함) 사용량 **+6.6%** 절감 (24시간 켜 두는 PC의 경우 **+8.4%**) |
| **모델 전환 가드** | 수동 전환 40회 중 29회 차단·안내. 차단된 전환 뒤 발생했던 재구축은 전체 사용량의 **8.2%**. (실제 절감액은 서브에이전트 위임 비율에 따름, 서브에이전트 시작 시 약 4.5만 토큰 소모) |
| **더 이른 자동 압축** | `autoCompactWindow`를 30만~40만 토큰으로 설정 시 **+17%** 절감 (신중한 가정 적용 시 **+10~12%**). 수치는 `cachekeeper compaction`으로 확인 가능 |

> [!NOTE]
> 세 가지 절감 효과는 상호 중복되므로 단순 합산할 수 없습니다 (예: Keep-Alive로 보존된 세션에서는 작은 컨텍스트 창이 줄여 줄 재구축 비용이 이미 사라짐). 실제 내 수치는 `/cachekeeper:audit` 명령으로 확인하세요.

---

## Q&A

**Q. 오래된 세션에도 핑을 보내나요?**  
A. 아닙니다. cachekeeper가 동작하는 동안 턴이 종료된 세션에만 핑이 전송됩니다. 앱을 재시작했다면 그 이후 사용된 세션만 대상이 됩니다. 세션별 한도(제작자 기록 기준 마지막 메시지 후 24시간)가 지나거나, 앱 종료 또는 PC 절전으로 1시간이 경과하면 즉시 중단됩니다.

**Q. 여러 세션을 병렬로 사용 중일 때 핑은 어떻게 가나요?**  
A. 각 세션마다 독립적인 타이머가 작동합니다. 해당 세션의 마지막 요청 55분 뒤 핑을 보내며, 세션별 마지막 활동 시점 기준 한도까지 유지됩니다. 특정 세션에 입력해도 다른 세션의 카운트에는 영향을 주지 않습니다. 세션 복귀 여부를 사전에 알 수 없으므로 실제 과거 복귀 빈도로 한도를 결정합니다. 제작자 기록에서는 핑의 70%가 복귀하지 않은 세션으로 전송되어 사용량의 0.6%가 소모되었으나, 나머지 핑이 사용량 7.5%에 해당하는 대규모 재구축을 방지했습니다.

**Q. 핑 한 번에 비용이 얼마나 드나요?**  
A. 구독 사용량 기준으로는 **약 1센트($0.01)** 수준입니다. 핑 자체는 수백 토큰만 사용하며 캐시 읽기는 거의 0으로 계산되기 때문입니다. API 정가 기준으로는 대화 전체를 다시 읽는 비용이 포함되어 30만 토큰 Opus 5.5 대화 기준 약 $0.07입니다 (동일 대화 전체 재구축 시 $2.40 소모).

**Q. 핑이 화면에 표시되나요?**  
A. 네. 대화창에 `cachekeeper keep-alive ping` 알림과 모델의 `(keep-alive)` 응답이 기록으로 남습니다. 핑 1회당 대화 컨텍스트가 수백 토큰 증가합니다.

**Q. 그냥 55분마다 무제한으로 핑을 보내면 안 되나요?**  
A. 밤마다 PC를 끄거나 절전 모드로 전환하는 환경에서는 무제한이어도 동일하게 +6.6% 절감됩니다. 그러나 24시간 켜 두는 PC에서는 다시 찾지 않는 세션에 며칠씩 핑이 전송되어 사용량의 0.4% 손실(컨텍스트 크기 제한마저 없으면 6.5% 손실)이 발생합니다. 한도 설정은 항시 켜져 있는 PC의 낭비를 방지하기 위한 안전장치입니다.

**Q. 컴퓨터가 잠들었거나 앱이 닫혀 있어도 동작하나요?**  
A. 동작하지 않습니다. 핑은 세션이 자체적으로 보내는 요청이므로 PC가 켜져 있고 세션이 열려 있어야 합니다. 1시간 이상 절전 후 깨어나면 캐시가 이미 만료되었으므로, 불필요한 재구축 비용을 내지 않고 조용히 물러납니다.

**Q. 캐시 수명 1시간은 Anthropic의 공식 규정인가요?**  
A. 네. [Claude Code 공식 문서](https://code.claude.com/docs/en/prompt-caching#cache-lifetime)에 따르면 메인 대화 캐시는 구독 요금제 한도 내에서 1시간, API 키 / 추가 크레딧(Usage credits) / 클라우드 제공자 환경에서는 5분입니다. 캐시를 읽는 요청이 발생할 때마다 타이머가 초기화됩니다. cachekeeper는 세션 기록에서 실제 캐시 수명을 판별하며, 5분 캐시 환경에서는 자동으로 꺼집니다.

**Q. API 키로 사용 중인 경우는 어떻게 되나요?**  
A. `promptCacheTtl`을 `1h`로 설정하지 않았다면 5분 캐시로 동작하므로 Keep-Alive는 비활성화되며, 가드 및 감사는 API 정가 기준으로 계산됩니다. 만약 `1h`로 설정하여 사용 중이라면 `CACHEKEEPER_BASIS=api`를 환경변수에 지정해 API 정가 기준으로 계산하도록 설정하세요.

**Q. Windows나 macOS에서도 동작하나요?**  
A. 네. 둘 다 Python 3.8 이상만 있으면 되고, Windows에서는 설치 후 앱을 다시 시작해야 합니다([Windows에서 사용하려면](#windows에서-사용하려면)). CI가 세 운영체제 모두에서 테스트를 실행하며(Windows는 Git Bash와 두 PowerShell 모두), 제작자는 Ubuntu에서 사용합니다.

**Q. 대화 데이터가 외부로 전송되나요?**  
A. 전혀 전송되지 않습니다. 로컬 PC의 대화 기록만 읽어 분석합니다. 플러그인 데이터 디렉터리의 로그 파일(`events.jsonl`)에는 모델명, 토큰 수, 결정 결과만 기록되며 프롬프트 내용은 일체 포함되지 않습니다.

**Q. 특정 기능만 끌 수 있나요?**  
A. 가능합니다. `~/.claude/settings.json`의 `env`에 다음 값을 지정합니다:
- Keep-Alive 끄기: `"CACHEKEEPER_KEEPALIVE": "0"`
- 모델 전환 가드 끄기: `"CACHEKEEPER_MODE": "off"` (차단하지 않고 경고만 보려면 `"warn"`)

---

## 왜 필요한가

Claude Code는 매 턴마다 대화 전체를 다시 전송하며, 프롬프트 캐싱을 통해 이를 경제적으로 처리합니다. 그러나 캐시가 깨지면 컨텍스트 전체를 새로 쓰게 됩니다. 발생하는 비용은 요금제 기준에 따라 크게 다릅니다.

- **API 정가 기준**: 캐시 읽기는 입력 단가의 0.1배 이하, 1시간 캐시 쓰기는 2배입니다.
- **구독 요금제 한도 기준**: 외부 실측 결과, 캐시 읽기는 입력 단가의 **0.18%**(거의 0) 수준이며, 쓰기는 일반 입력 단가(1배)로 계산됩니다.

### 제작자의 12.7일간 실제 사용량 분석
> 2026-09-11 ~ 09-24, 메인 세션 152개, 총 요청 9,658건 (그중 94%가 1시간 캐시)

| 구분 | 구독 사용량 비중 | API 정가 비중 |
|---|---|---|
| **캐시 읽기** | 4.6% | 54.8% |
| **캐시 쓰기 (재구축)** | **51.0%** | 31.5% |
| **출력** | 44.4% | 13.7% |

### 캐시 쓰기(재구축) 원인별 분포

| 재구축 원인 | 횟수 | 컨텍스트 중간 크기 | 구독 사용량 비중 | API 정가 비중 |
|---|---|---|---|---|
| **모델 전환 (`/model`)** | 35회 | 54.5만 토큰 | **12.5%** | 7.7% |
| **1시간 초과 휴식 (TTL 만료)** | 42회 | 45.6만 토큰 | **11.8%** | 7.3% |
| 기타 (도구 정의 변경, 버전 업그레이드, 이미지 삽입) | 17회 | 63.4만 토큰 | 4.8% | 3.0% |
| 세션 신규 시작 / 재개 | 18회 | 14.7만 토큰 | 4.1% | 2.6% |
| 자동 모델 전환, Effort 변경, 컨텍스트 압축 | 13회 | - | 2.3% | 1.4% |

읽기가 거의 무료인 구독제에서는 **재구축이 한 턴에서 발생할 수 있는 가장 치명적인 낭비**입니다. 가드와 Keep-Alive가 방어하는 두 가지 원인이 전체 사용량의 **24.3%(약 4분의 1)**를 차지했습니다. 45만 토큰 세션에서 Opus 5와 Fable 5.1 사이를 한 번 오가면 대화 전체를 새 모델에 다시 캐싱합니다 (Fable 5.1 기준 구독 사용량 약 $4.50, API 정가 약 $9 상당). 상세한 실측 기록은 [docs/measurement-2026-09-23.md](docs/measurement-2026-09-23.md)에서 확인할 수 있습니다.

---

## 두 가지 잣대

cachekeeper의 모든 금액 추산(가드 안내, 감사 리포트, Keep-Alive 및 압축 시뮬레이션)은 두 가지 과금 기준 중 하나를 따릅니다.

| 잣대 (`basis`) | 캐시 읽기 | 캐시 쓰기 (5분 / 1시간) | 캐시되지 않은 입력 | 출력 |
|---|---|---|---|---|
| `subscription` | 입력 단가의 0.0018배 | 1배 / 1배 | 1배 | 출력 단가 |
| `api` | 입력 단가의 0.1배 이하 | 1.25배 / 2배 | 1배 | 출력 단가 |

### `subscription` 잣대의 산출 근거
구독 요금제의 한도 차감 공식은 비공개이므로 외부 실측 자료를 기반으로 역산합니다.
- [she-llac.com](https://she-llac.com/claude-limits)(2026년 1월): 미반올림 사용량 역산 결과 캐시 읽기 비용을 입력 단가의 0.18%로 추정 (80% 신뢰구간: 0~0.5%).
- alldonesites 사용량 추적(Max 20x 계정 4개, 2026-09-21): Fable 5.1이 Opus 5의 2.11배로 계산되어 정가 비율과 유사함을 확인.
- 1시간 캐시 쓰기도 일반 입력 단가로 계산된다는 점과 Opus 5.5가 정가 비율을 따른다는 가정 적용.

> [!NOTE]
> `subscription` 기준 금액은 차감되는 사용량을 API 정가 기준 달러 가치로 환산한 수치이며, 실제 청구 요금이 아닌 요금제 한도 소진 비중을 직관적으로 보여주기 위한 지표입니다.

### 기본 잣대 결정 방식
기본적으로 세션의 캐시 정책을 따릅니다:
- Claude Code 2.1.280은 구독 한도 내 메인 세션에 **1시간 캐시**를 부여하므로 `subscription` 적용.
- API 키 사용 또는 추가 크레딧 상태에서는 **5분 캐시**가 적용되므로 `api` 적용.
- API 환경에서 `ENABLE_PROMPT_CACHING_1H` 등을 활성화한 경우 `CACHEKEEPER_BASIS=api`로 수동 고정할 수 있습니다. 명령 실행 시 `--basis` 옵션으로도 지정 가능합니다.

---

## 모델 전환 가드

전환 비용은 Claude Code가 이미 계산하고 있습니다. `PreModelSwitch` Hook 입력값에 `prompt_cache_warm`, `context_tokens`, `cache_ttl`, `estimated_cache_write_usd`가 포함되어 전달됩니다.

캐시가 유효하고 재작성 예상 비용이 **$1 이상**일 경우, cachekeeper는 전환을 차단하고 다음과 같은 대화창을 띄웁니다.

```text
cachekeeper: opus-5 → fable-5-1로 바꾸면 지금 살아 있는 캐시(1h)를 버리고 대화 452k 토큰을
fable-5-1에 다시 씁니다 — 약 $4.52 (구독 사용량 기준: 캐시 쓰기를 입력 단가로 셈). 이 작업만
fable-5-1로 하려면 하려던 요청을 그대로 보내세요. fable-5-1 서브에이전트에 맡길지 먼저 묻고,
끝나면 지금 모델(opus-5)로 이어집니다. 세션 모델 자체를 바꾸려면 120초 안에
`/model claude-fable-5-1`를 입력하세요. 모델 선택기에 fable-5-1 표시가 남아 있어도 세션은
opus-5 그대로입니다.
```

### 환경별 동작 방식
- **터미널 세션**: Claude Code가 위 안내 문구와 함께 확인 대화상자(Modal)를 띄웁니다. 터미널에서는 캐시가 살아 있으면 Claude Code도 원래 `/model` 전환 전에 확인을 묻습니다([공식 문서](https://code.claude.com/docs/en/prompt-caching#switching-models)). `PreModelSwitch` Hook의 `ask`는 그 대화상자를 띄우는 것이고, cachekeeper는 여기에 금액과 대안을 담습니다.
- **Claude 데스크톱 앱 및 Headless (`-p`) 세션**: 확인 창이 지원되지 않습니다. 전환 시도가 위 문구와 함께 차단되며, **안내문에 명시된 `/model <모델명>` 명령어를 120초 안에 직접 입력하면 확인으로 인정되어 전환됩니다.** (2026-09-23 데스크톱 앱 검증 완료)

> [!WARNING]
> 데스크톱 앱의 UI 모델 선택기로는 확인이 일정하지 않습니다.
> - **턴과 턴 사이에 차단된 전환**: UI 선택기에는 새 모델이 선택된 것처럼 표시되지만 실제 세션은 이전 모델로 유지됩니다. 이 상태에서 다시 클릭해도 요청이 전송되지 않습니다 (2026-09-23 확인).
> - **턴 진행 중에 차단된 전환**: 앱이 선택기를 세션 모델로 되돌립니다 (데스크톱 앱 2.2553.13 로그의 `record restored`). 이때 새 모델을 다시 고르면 Claude Code에 전달되어 전환이 확정됩니다. 2026-09-24에 차단 6초 뒤 다시 고르자 제작자의 세션이 실제로 바뀌었습니다.
>
> 표시가 어긋난 경우 현재 세션의 실제 모델을 UI에서 다시 선택해 동기화해 주세요.

### 가드 적용 조건 및 기준
- 1시간 캐시에서는 2배 쓰기 할증을 제외한 `subscription` 기준 금액을 표시하며, 5분 캐시이거나 `CACHEKEEPER_BASIS=api`인 경우 API 정가 기준 금액을 표시합니다.
- $1 기준 역시 동일한 잣대로 측정되므로, 구독 사용량 기준으로는 Opus 5.5 약 25만 토큰, Fable 5.1 약 10만 토큰부터 가드가 동작합니다 (API 정가 기준: 12.5만 / 5만).
- 이전 버전(0.6.0 이전)처럼 더 민감하게 동작시키려면 `CACHEKEEPER_MIN_USD=0.5`로 설정하세요.
- **조용히 통과하는 경우**: 캐시가 이미 만료된 경우, 작은 컨텍스트, 시스템 자동 폴백, 세션 재개 시의 모델 복원 등.
- 서브에이전트는 메인 캐시를 공유하지 않고 자체 캐시를 생성하므로 메인 캐시 손실이 없습니다.

### 이 작업만 다른 모델로 위임하기
전환이 차단되었을 때 더 저렴한 대안을 제시합니다. **다른 모델에 맡기려던 프롬프트를 다음 메시지로 그냥 입력하면, 해당 모델의 서브에이전트에 맡길지 먼저 묻습니다.**
- 맡기면 서브에이전트가 그 요청 하나만 단발성으로 처리합니다. 끝나면 메인 모델이 결과를 전하거나 반영하고 세션 모델로 대화를 이어 갑니다. 맡기지 않으면 메인 모델이 평소처럼 답합니다.
- 세션의 메인 모델과 캐시는 그대로 유지됩니다. 묻고, 지시문을 쓰고, 끝난 뒤 이어 가는 것 모두 메인 모델이 하므로, 메인 모델로 돌아오는 데 두 번째 전환도 두 번째 재구축도 필요 없습니다.
- `UserPromptSubmit` Hook이 메인 모델에게 이 질문(AskUserQuestion 도구, 안내문과 같은 언어로)과 맡길 때의 방법(Agent 도구에 요청한 모델 그대로, 예: `model: "claude-fable-5-1"`, 안 되면 별칭 `fable`)을 함께 전달합니다.
- 답할 사람이 없는 `claude -p` 실행과 Agent SDK 앱(`sdk-`로 시작하는 entrypoint)에서는 묻지 않고 바로 서브에이전트에 맡깁니다.
- 방향에 관계없이 동작합니다 (예: Fable에서 `/model claude-opus-5` 입력 시 Opus 5 서브에이전트 위임 제안).
- 서브에이전트는 메인 대화 전체를 직접 보지 못하므로 메인 모델이 핵심 맥락을 요약하여 전달합니다. 작업 종료 후 다음 메시지부터는 정상 처리됩니다.

> [!NOTE]
> 2026-09-23 Opus 5.5 메인 세션에서 정상 위임을 확인했습니다 (`Agent`, `model: "sonnet"` 실행 후 "This session is still on Opus" 응답). 단, 메인 모델이 Haiku 4.5일 때는 위임 지시를 3회 모두 무시하는 현상이 있었습니다. 이 제안은 메인 모델의 지시 준수 능력에 의존합니다. 맡기기 전에 묻는 단계는 0.8.0에서 새로 추가되었으며, 아직 실제 세션에서 확인하지 않았습니다.

모든 전환 요청과 결정 이력은 플러그인 데이터 디렉터리의 `events.jsonl`에 안전하게 기록되며, `cachekeeper events` 명령으로 조회할 수 있습니다.

---

## 감사(audit)

audit의 역할은 **cachekeeper가 사용량을 얼마나 줄이는지(절감률)를 내 기록으로 재현해 보여 주는 것**입니다. Keep-Alive는 핑 비용을 뺀 순절감률을 보여 줍니다. 가드는 절감액이 사용자의 선택에 달려 있어서, 질문에 걸린 사용량 비중을 보여 줍니다. 제작자 기록(2026-09-11 ~ 09-24)의 결과는 다음과 같습니다.

```text
모델 전환 경고를 켰다면
  직접 한 전환 41번 중 캐시가 살아 있고 재구축이 $1 이상인 30번에 물었을 것이고, 그중 26번은 실제로 재구축됐습니다 — 사용량의 7.9%가 그 결정에 걸려 있었습니다.

55분 keep-alive를 켰다면 (1시간 TTL 세션, 8시간 한도)
  핑 1222번(돌아오지 않은 세션에 나갔을 핑 포함)에 사용량의 1.1%를 쓰고, 만료 재구축 33번(사용량의 7.5%)을 막아 순효과는 +6.4%입니다.
  실제로 나간 keep-alive 핑: 27번, 사용량의 0.1%
```

지금 쓰는 정책(`auto`가 고른 것)의 절감률은 `cachekeeper keepalive`로 볼 수 있습니다 (제작자 기록: 10만 토큰 이상 세션, 최대 24시간, 순효과 +8.0%).

```bash
# 최근 30일 기록을 로케일 언어로 분석
cachekeeper audit

# 최근 7일 기록을 JSON 형식으로 출력
cachekeeper audit --days 7 --json
```

- 세션 내부에서는 `/cachekeeper:audit`로 실행 가능합니다.
- `cachekeeper keepalive`는 휴식 시간 분포와 가장 이상적인 정책을 제안합니다.
- `~/.claude/projects/*/*.jsonl` 경로의 메인 세션을 파싱하며, 세션 재개로 인해 복사된 중복 응답은 1회만 계산합니다.

### 제공하는 4가지 핵심 분석 데이터
1. **사용량 구성**: 캐시 읽기, 캐시 쓰기, 출력, 일반 입력 비중
2. **모든 재구축 원인 추적**: 신규 세션, 직접/자동 모델 전환, Effort 변경, 압축, TTL 만료, 기타
3. **가드 시뮬레이션**: 실제 전환 중 가드가 물어보았을 횟수와 방지할 수 있었던 사용량
4. **55분 Keep-Alive 시뮬레이션**: 핑 소모 비용과 방어 가능한 만료 재구축 비교 (복귀하지 않은 세션의 핑 비용 포함, `claude -p` 배치 세션 제외)

---

## 세션을 얼마나 키울 것인가

Claude Code는 매 턴마다 대화 전체를 다시 읽으므로, **API 정가 기준으로는 세션이 길어질수록 턴마다 읽기 비용이 누적**됩니다.
- 제작자 기록 기준: 턴당 재전송 토큰 중간값은 40만 토큰이었으며, 컨텍스트 중 30만 토큰을 초과하는 부분을 읽는 데만 전체 사용량의 24%가 소모되었습니다.
- 반면 **구독 사용량 기준으로는 읽기 비용이 거의 들지 않으므로**, 긴 컨텍스트는 장시간 휴식 후 복귀하거나 모델을 바꿀 때 발생하는 '재구축' 시점에만 비용이 발생합니다.

기본적으로 Claude Code는 컨텍스트 창(현재 100만 토큰)이 거의 찼을 때만 자동 압축을 수행합니다 (제작자 기록 기준 약 97만 토큰 시점). `autoCompactWindow` 설정(또는 `CLAUDE_CODE_AUTO_COMPACT_WINDOW`, 10만~100만)으로 압축 시점을 앞당길 수 있습니다.

```bash
cachekeeper compaction
```

과거 세션들을 다양한 창 크기로 가상 재생하여 절감액과 비용을 산출합니다.

### 컨텍스트 창 크기별 시뮬레이션 결과 (제작자 12.7일 기록)
> 실제 압축 15회 실측치 기준: 압축 직후 7만 토큰에서 재개, 신규 쓰기 3.5만 토큰, 요약 출력 5.3천 토큰, 파일 재읽기 1.4만 토큰 발생 (괄호 안은 파일 재읽기 4.5만, 요약 1.5만을 가정한 신중한 추정치).

| 압축 창 크기 | 일평균 압축 횟수 | 구독 사용량 순효과 | API 정가 순효과 |
|---|---|---|---|
| **20만 토큰** | 16회 | **+16%** (−3%) | **+46%** (+36%) |
| **30만 토큰** | 9회 | **+17%** (+10%) | **+43%** (+38%) |
| **40만 토큰** | 5회 | **+17%** (+12%) | **+38%** (+34%) |
| **60만 토큰** | 4회 | **+15%** (+11%) | **+29%** (+27%) |
| **80만 토큰** | 2회 | **+5%** (+3%) | **+15%** (+13%) |

- **API 정가**: 절감 효과의 대부분이 '매 턴마다 줄어든 대화 읽기 비용'에서 나옵니다.
- **구독 사용량**: 절감 효과의 대부분이 '휴식/전환 후 작아진 크기로 재구축하는 이점'에서 나오므로, **Keep-Alive의 절감 효과와 중복**됩니다.
- **품질 고려**: 압축이 잦을수록 컨텍스트의 세부 맥락이 유실될 위험이 큽니다. 작업 단위가 끝났을 때 사용자가 직접 `/compact`로 남길 내용을 지정해 정리하는 것이 가장 안전하며, 자동 압축 창은 이를 놓쳤을 때의 안전망으로 활용하는 것이 좋습니다.

---

## keep-alive

1시간 이상 자리를 비웠다 복귀하면 대화 전체를 다시 캐싱해야 합니다. cachekeeper는 비운 시간 동안 짧은 핑으로 캐시를 유지합니다.

### 작동 메커니즘
- 턴이 끝나면 `Stop` Hook이 백그라운드 대기에 들어갑니다 (`asyncRewake` 기능: 종료 코드 2 반환 시에만 Claude Code가 모델을 깨움).
- 마지막 요청 시작 후 **55분**이 되면 모델을 깨우고, 모델은 `(keep-alive)` 한 단어로 응답하여 1시간 캐시 타이머를 갱신합니다.
- **비용 비교 (30만 토큰 Opus 5.5 대화 기준)**:
  - 구독 요금제: 핑 1회 약 **$0.007** vs 재구축 **$1.20** (제작자 핑 15회 평균: 입력 511토큰, 출력 123토큰)
  - API 정가: 핑 1회 약 **$0.07** vs 재구축 **$2.40**

### 발송 조건 및 안전장치
- 1시간 캐시를 사용하고, 일정 크기 이상인 세션에서, 정해진 횟수만큼만 핑을 보냅니다.
- 사용자가 메시지를 입력하면 타이머 카운트가 초기화됩니다.
- **즉시 물러나는 경우**: 사용자 입력 발생, 다른 턴 완료, 모델 변경, `/compact` 실행 후, PC 절전으로 1시간 경과, `claude -p` 및 Agent SDK 환경.
- **무한 반복 방지**: 실패 가운데 무한 반복으로 이어지는 것은 exit 2뿐입니다. Claude Code 2.1.280은 종료 코드 2일 때만 모델을 깨우므로(코드에서 확인), 턴이 끝날 때마다 exit 2를 내는 `Stop` Hook은 모델을 끝없이 깨웁니다 ([anthropics/claude-code#96087](https://github.com/anthropics/claude-code/issues/96087), [#96148](https://github.com/anthropics/claude-code/issues/96148). 둘 다 스크립트를 열지 못한 Python의 exit 2였습니다). 그래서 cachekeeper의 Hook은 요청받았을 때만 exit 2를 냅니다. Keep-Alive는 핑할 때 자기만의 코드 75로 끝나고, `Stop` Hook 명령은 이 코드만 2로 바꿉니다. 그 밖의 모든 종료(파일이 사라짐, Python 없음, 오류, 스크립트를 열지 못한 셸. Ubuntu의 `sh`는 이때도 exit 2를 냅니다)는 0으로 끝나며, 모델 전환과 프롬프트 Hook은 답을 JSON으로 전달하므로 항상 0으로 끝납니다.

### 정책 최적화 시뮬레이션 (`auto` 모드)
`cachekeeper keepalive`는 실제 복귀 패턴을 분석하여 최적의 정책을 산출합니다:
- **구독 사용량 기준**: 10만 토큰 이상 세션을 최대 24시간 유지 시, 핑 1,981회(2.5% 소모)로 재구축 40회(11.0% 절감)를 방어하여 **순효과 +8.5%** 달성 (최대 3시간 유지 시 +7.0%).
- **API 정가 기준**: 30만 토큰 이상 세션을 최대 2시간 유지 시, 핑 161회(1.5% 소모)로 재구축 20회(3.9% 절감)를 막아 **순효과 +2.4%** 달성 (24시간 유지 시 핑 읽기 누적으로 오히려 −6.9% 손실).
- **PC 절전 반영 실측**: 밤에 PC를 끄거나 절전하는 실제 가동 환경에서는 3시간 유지 시 +6.2%, 24시간 유지 시 +6.6%로 큰 차이가 없었습니다.

### Keep-Alive 환경 변수

| 변수명 | 기본값 | 설명 |
|---|---|---|
| `CACHEKEEPER_KEEPALIVE` | `auto` | `auto`: 사용 기록 기반 최적 정책 자동 적용 (매일 갱신)<br>`1`: 아래 고정 설정값 사용<br>`0`: 기능 비활성화 |
| `CACHEKEEPER_KEEPALIVE_MIN_TOKENS` | `100000` | 수동 모드(`1`) 시: 유지할 최소 컨텍스트 크기 (토큰) |
| `CACHEKEEPER_KEEPALIVE_HOURS` | `3` | 수동 모드(`1`) 시: 마지막 메시지 후 최대 유지 시간 (시간) |
| `CACHEKEEPER_KEEPALIVE_MINUTES` | `55` | 핑 전 대기 시간 (분) |

> [!NOTE]
> `auto` 모드는 `Stop` Hook이 하루 한 번 백그라운드에서 최적 정책을 자동 계산합니다 (효과 차이가 1% 미만이면 핑 횟수가 적은 보수적 정책 선택). 기록된 휴식 구간이 10개 미만이거나 절감 효과가 없는 경우 작동을 중단합니다.

### 실측 결과 및 확인
2026-09-23 데스크톱 앱 실측 결과: 5.7만 토큰 Opus 5.5 세션에서 55분, 110분 시점의 핑이 정상적으로 캐시를 읽었으며($0.014 소모), 112분 후 사용자가 보낸 요청은 $0.46 재구축 비용 대신 **$0.015**로 신속하게 처리되었습니다. 전체 이력은 `cachekeeper events`로 확인할 수 있습니다.

### 터미널 상태 표시줄

터미널에서는 `cachekeeper statusline`이 Claude Code 상태 표시줄에 캐시 남은 시간과 다음 핑을 보여 줍니다.

```
캐시 312k · 36분 남음 · 다음 핑 31분 후 (1/26)
```

- `312k`는 캐시가 식으면 다음 요청이 다시 쓸 크기이고, `(1/26)`은 마지막 메시지 이후 현재 정책이 허용하는 26번 가운데 첫 번째 핑이라는 뜻입니다.
- 그 밖의 표시: `곧 핑`, `핑 한도 (26/26)`, `핑 안 함 (100k 미만)`, `keep-alive 꺼짐`, `(5분 캐시)` (Keep-Alive는 1시간 캐시만 유지), `캐시 식음 · 다음 요청에 312k 다시 씀`.
- 언어는 `CACHEKEEPER_LANG`이나 `LANG`을 따릅니다.

플러그인은 상태 표시줄을 설정할 수 없으므로 `~/.claude/settings.json`에 직접 추가합니다. 경로는 마켓플레이스에 있는 플러그인 사본이라 버전이 바뀌어도 그대로입니다.

```json
{
  "statusLine": {
    "type": "command",
    "command": "~/.claude/plugins/marketplaces/cachekeeper/bin/cachekeeper statusline",
    "refreshInterval": 30
  }
}
```

- **`refreshInterval`**: 30초마다 다시 실행해 자리를 비운 동안에도 남은 분이 줄어듭니다. 없으면 이벤트가 있을 때와 캐시가 만료될 때만 갱신됩니다.
- **Windows**: Git Bash가 있으면 위 명령 그대로 동작합니다. 없으면 `"command": "powershell -NoProfile -ExecutionPolicy Bypass -File C:/Users/<이름>/.claude/plugins/marketplaces/cachekeeper/bin/cachekeeper.ps1 statusline"` (경로 구분자는 `/`).
- **이미 상태 표시줄을 쓰고 있다면**: 쓰던 스크립트에서 이 명령을 불러 한 줄로 이어 붙입니다. 예: `echo "$(기존 내용) · $(printf '%s' "$input" | ~/.claude/plugins/marketplaces/cachekeeper/bin/cachekeeper statusline)"`
- 대화 기록의 끝부분과 플러그인 자체 파일만 읽고, 아무것도 쓰거나 보내지 않습니다. 12MB 기록에서 약 0.1초 걸립니다(실측). 상태 표시줄에 캐시 상태를 넘겨 주는 Claude Code 2.1.251 이상이 필요합니다.

> [!NOTE]
> 데스크톱 앱은 상태 표시줄 명령을 실행하지 않습니다. 2026-09-24 실측(Claude Code 2.1.280)에서 `refreshInterval` 5초로 1분 44초 동안 한 번도 실행되지 않았고, 코드상으로도 상태 표시줄은 터미널 화면에만 있습니다. 그래서 터미널 전용입니다.

---

### 다른 Keep-Alive 도구와의 비교

첫 줄은 cachekeeper이고, 나머지는 2026-09-24 기준 각 README에 적힌 내용입니다.

| 프로젝트 | 핑 구현 방식 | 실행 시점 및 한도 | 계산 기준 |
|---|---|---|---|
| **cachekeeper** | 플러그인에 들어 있는 `asyncRewake` `Stop` Hook. 데스크톱 앱에서 실측, Linux·macOS·Windows는 CI로 테스트 | 마지막 요청 55분 후. 최소 크기와 마지막 메시지 뒤 한도를 내 기록으로 매일 다시 정함 (고정 설정: 10만 토큰, 3시간) | 구독 사용량 (`CACHEKEEPER_BASIS=api`면 API 정가) |
| **[Delitefully/claude-keepwarm](https://github.com/Delitefully/claude-keepwarm)** | Function hooks 모듈 (`CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1` 필요) 또는 백그라운드 모니터 | 45분 미입력 시, 최대 8회 (약 8시간), 2만 토큰 이상 | API 정가 |
| **[FiredMosquito831/claude-cache-warm](https://github.com/FiredMosquito831/claude-cache-warm)** | 플러그인 모니터 (CLI 대화형 전용). 비대화형은 `CronCreate` 예약 작업 | 서브에이전트/백그라운드 명령 실행 중 위주. 50분 주기, 최대 3시간, 2만 토큰 이상 | API 정가 |
| **[santiquiroz/claude-prompt-cache-keepalive](https://github.com/santiquiroz/claude-prompt-cache-keepalive)** | OS 절전 방지 잠금 + 타이머 사다리 ("afk" 입력 시 구동) | 사용자가 설정한 사다리 시간만큼 | API 정가 |
| **[Pan1127/cc-cache-keepalive](https://github.com/Pan1127/cc-cache-keepalive)** | systemd 타이머 + 복제(Fork) 세션 핑 (Linux/tmux 전용) | 마지막 활동 50분 후 | - |
| **[cnighswonger/claude-code-coffee](https://github.com/cnighswonger/claude-code-coffee)** | `/coffee 30`, `/coffee overnight` 등 `CronCreate` 수동 예약 | 지정한 휴식 시간 동안 | API 정가 |
| **[yujiachen-y/claude-code-cache-keepalive](https://github.com/yujiachen-y/claude-code-cache-keepalive)** | `Stop` hook 4분 대기 후 턴 강제 연장 | 5분 캐시용: 최대 7회 (약 28분) | API 키 과금 (구독 시 사용 금지 안내) |
| **[demouo/claude-code-cache-keepalive](https://github.com/demouo/claude-code-cache-keepalive)** | 플러그인 모니터(Monitor 도구)가 `Stop` Hook이 남긴 시각을 감시 (CLI 대화형 세션 전용) | 50분 미입력 시, 미입력 12시간까지 | API 정가 |
| **[159753a52/claude-cache-keepalive](https://github.com/159753a52/claude-cache-keepalive)** | Node.js `asyncRewake` `Stop` hook (settings.json에 직접 추가) | 턴 종료 50분 후, 최대 3회, 5만 토큰 이상, claude.ai 구독만 | - |
| **[ARahim3/cachebeat](https://github.com/ARahim3/cachebeat)** | `/cachebeat`가 백그라운드 셸 작업을 띄우고, 50분 미입력 시 작업이 끝나며 Claude를 깨움. Claude가 작업을 다시 띄움 | 50분 미입력 시, 켠 뒤 8시간까지 (기본값). 1시간 캐시 전용 | - |
| **[karanb192/cache-tax](https://github.com/karanb192/cache-tax)** | Function hooks 모듈(`CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1` 필요)이 도구 없는 세션 복제본(fork)을 보냄. 캐시가 식은 뒤 보낸 메시지를 한 번 막고 재작성 비용을 보여 줌. 상태 표시줄 | `/keepwarm`으로 켠 시간 동안(기본 6시간, 또는 세션마다 자동) 50분 미입력 시. 캐시가 식어 다시 쓴 뒤 최소 3시간 | API 정가 |
| **[bpeers01/tkr-releases](https://github.com/bpeers01/tkr-releases)** | 바이너리로 배포되는 토큰 절약 도구 모음 안의 `asyncRewake` 감시 Hook. v5.31부터 큰 캐시를 다시 쓰게 되는 모델 전환 전에 경고 | 설정한 미입력 시간 후, 1시간 캐시에서. 작은 컨텍스트는 건너뜀 | - |
| **[luoxiaoxin123/cc-keepalive-desktop](https://github.com/luoxiaoxin123/cc-keepalive-desktop)** | 프로젝트 폴더별 `HTTPS_PROXY`로 거는 로컬 프록시가 세션 요청을 `max_tokens=1`로 다시 보냄. Windows 전용, 데스크톱 앱용 | 켠 세션에서 50분마다(최대 58분). 58분 넘게 미입력 시 중단 | - |

> [!IMPORTANT]
> **복제(Fork) 세션 방식의 한계 (Delitefully 실측)**:  
> 기존 세션에 `claude --resume <id> --fork-session -p`를 실행한 결과, 시스템 프롬프트에 세션 고유 식별자가 포함되어 **기존 캐시 읽기 0회, 54,300 신규 토큰 작성**이 발생했습니다. 즉, 복제 세션은 원본 세션의 캐시를 데우지 못합니다.
> 단, cache-tax처럼 Claude Code가 실행 중인 세션의 기록으로 만드는 복제본은 다릅니다. cache-tax는 한 번 잰 복귀에서 캐시 157k 토큰을 읽었습니다.

핑 대신 다른 길을 택한 도구도 있습니다. [navaro1/warmfold](https://github.com/navaro1/warmfold)와 [intenex/claude-idle-compactor](https://github.com/intenex/claude-idle-compactor)는 캐시가 만료되기 전에 쉬고 있는 세션을 압축해, 돌아왔을 때 대화 전체 대신 요약만 다시 쓰게 합니다. [ruodou233/claude-cache-keepalive](https://github.com/ruodou233/claude-cache-keepalive)는 스킬과 설계 문서로, 에이전트가 먼저 환경을 재 본 뒤 핑을 설정합니다 (구독에서는 55분 간격, 휴식당 최대 2번).

*(cachekeeper가 하지 않는 것: 핑 메시지 숨기기, 데스크톱 앱에서의 카운트다운 표시(데스크톱 앱은 상태 표시줄을 실행하지 않음), 캐시가 식은 뒤 보낸 메시지 막기, 만료 전 자동 압축, OS 강제 절전 방지, 5분 캐시 살리기)*

---

## 요구 사항과 설정

- **Python 3.8 이상** (미설치 시 Hook이 개입하지 않고 모든 동작을 통과시킵니다).
- **Claude Code 2.1.280 이상** (`PreModelSwitch` 및 `asyncRewake` 지원).
- 로컬 저장소 코드로 직접 테스트: `claude --plugin-dir /path/to/cachekeeper`
- **Linux, macOS, Windows** 지원. CI가 세 운영체제 모두에서 테스트를 실행합니다([테스트](#테스트)).
- Windows에서는 Git Bash가 있으면 Git Bash로, 없으면 PowerShell로 실행됩니다. 준비 방법은 [Windows에서 사용하려면](#windows에서-사용하려면)을 보세요.

### 환경 변수 목록 (`~/.claude/settings.json`)

```json
{
  "env": {
    "CACHEKEEPER_MODE": "ask",
    "CACHEKEEPER_MIN_USD": "1.0",
    "CACHEKEEPER_KEEPALIVE": "auto"
  }
}
```

| 환경 변수 | 기본값 | 허용 값 및 설명 |
|---|---|---|
| `CACHEKEEPER_MODE` | `ask` | `ask` (차단 후 질의), `warn` (차단 없이 경고만 출력), `off` (비활성화) |
| `CACHEKEEPER_BASIS` | 세션 캐시 기준 | `subscription` 또는 `api` (비용 계산 [잣대](#두-가지-잣대) 강제 지정) |
| `CACHEKEEPER_MIN_USD` | `1.0` | 가드가 개입할 최소 재구축 예상 금액 ($) |
| `CACHEKEEPER_MIN_TOKENS` | `100000` | 신규 모델의 가격 정보를 알 수 없을 때 사용하는 토큰 기준치 |
| `CACHEKEEPER_CONFIRM_SECONDS` | `120` | 모델 전환 재입력 확인 유효 시간 (초) |
| `CACHEKEEPER_OFFER_SECONDS` | `900` | 전환 차단 후 다음 메시지에서 서브에이전트에 맡길지 묻는 유효 시간 (초) |
| `CACHEKEEPER_LANG` | 시스템 `LANG` | `ko` 또는 `en` |

---

## 한계

1. **단일 모델 캐시 추적**: `prompt_cache_warm`은 현재 활성화된 모델의 캐시 상태만 가리킵니다. TTL 만료 전 이전에 사용했던 모델로 되돌아가는 경우 캐시가 적중할 수 있으므로, 실제 재구축 비용은 경고보다 적을 수 있습니다 (제작자 29회 경고 중 25회가 실제 재구축으로 이어짐).
2. **재현 시뮬레이션의 특성**: 감사 및 시뮬레이션 결과는 사용자의 과거 행동을 가상으로 모사한 추정치이며, 실제 절감량은 사용자의 최종 선택에 따라 달라집니다.
3. **구독 사용량 잣대의 변동성**: 구독제 과금 공식은 공식 공개 자료가 아닌 외부 실측치이므로 Anthropic의 정책 변경에 따라 변동될 수 있습니다.
4. **대화창 내 핑 표시**: Keep-Alive 핑은 실제 대화상에 짧은 메시지로 기록되며 일반 턴과 동일하게 사용량에 반영됩니다.
5. **PC 상태 의존성**: Keep-Alive는 PC가 깨어 있고 세션이 열려 있어야 동작합니다. 절전으로 1시간이 지나버린 경우에는 재구축 비용을 내는 대신 물러납니다.
6. **Hook 범위의 한계**: 가드는 `PreModelSwitch` Hook으로 유입되는 전환만 감지합니다. 모델의 Effort 변경 또한 대부분의 모델에서 캐시를 무효화하지만(Opus 5.5 및 Fable 5.1 제외), 이는 Claude Code 자체 확인 창이 처리합니다.

---

## 테스트

```bash
python3 -m unittest discover -s tests
```

`tests/test_runner.py`는 Claude Code가 하는 그대로 Hook과 CLI를 실행합니다.
- hooks.json의 명령을 Claude Code가 쓰는 각 셸(macOS와 Linux는 `/bin/sh -c`, Windows는 Git Bash, Git Bash가 없을 때의 PowerShell 7과 Windows PowerShell 5.1)로 실행하고, 이벤트는 stdin으로 넣으며, Windows에서 Python이 파이프에 쓰는 코드페이지(cp1252, cp949)를 적용합니다.
- Keep-Alive가 핑 메시지와 함께 exit 2로 끝나는지(`asyncRewake`가 모델을 깨우는 조건), Keep-Alive 자신의 코드만 2가 되는지, 플러그인 파일이 없을 때 어떤 Hook도 exit 2를 내지 않는지 확인합니다.
- CI는 모든 테스트를 Ubuntu, macOS, Windows에서 Python 3.8과 3.12로 실행합니다(macOS는 3.12만). Windows에서는 Git Bash(Windows 경로)와 두 PowerShell로 실행합니다.

---

## 라이선스

본 프로젝트는 [MIT 라이선스](LICENSE)를 따릅니다.
