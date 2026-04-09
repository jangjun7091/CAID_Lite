# CAID Lite

**Natural Language → CadQuery → STEP/STL** 자동 생성 연구 엔진

자연어 프롬프트를 입력하면 LLM이 CadQuery Python 코드를 생성하고, 안전한 샌드박스 환경에서
실행하여 3D CAD 파일(STEP/STL)을 출력합니다. 다중 에이전트 구조, 자동 수정 루프,
브라우저 기반 3D 뷰어를 모두 포함한 독립형 파이프라인입니다.

> CAID 멀티에이전트 프로젝트와 의도적으로 분리되어, 독립 개발·벤치마크 후 드롭인 백엔드로
> 통합할 수 있도록 설계되었습니다.

---

## 목차

1. [주요 기능](#주요-기능)
2. [아키텍처 개요](#아키텍처-개요)
3. [디렉터리 구조](#디렉터리-구조)
4. [설치](#설치)
5. [빠른 시작](#빠른-시작)
6. [LLM 공급자 설정](#llm-공급자-설정)
7. [파이프라인 상세](#파이프라인-상세)
8. [멀티에이전트 모드](#멀티에이전트-모드)
9. [CAD 패턴 라이브러리](#cad-패턴-라이브러리)
10. [GUI](#gui)
11. [API 서버](#api-서버)
12. [테스트](#테스트)
13. [데이터셋 로그](#데이터셋-로그)

---

## 주요 기능

| 기능 | 설명 |
|---|---|
| **공급자 무관 LLM 레이어** | Qwen(기본) / OpenAI / Anthropic / 로컬 서버 — 코드 변경 없이 전환 |
| **안전한 샌드박스 실행** | 타임아웃·격리 서브프로세스, OCC 크래시가 메인 프로세스에 영향 없음 |
| **지오메트리 검증** | isValid, 부피, 솔리드 여부 등 하드/소프트 체크 |
| **자동 수정 루프** | 실행·검증 실패 시 LLM 유도 수정 최대 3회 반복 |
| **멀티에이전트 파이프라인** | Architect → Designer → Critic 4단계 생성 구조 (옵션) |
| **CAD 패턴 라이브러리** | 21종 YAML 패턴으로 생성 품질 향상 |
| **3-pane 브라우저 GUI** | Parts Shelf / Three.js 3D 뷰어 / AI 채팅 |
| **FastAPI REST + SSE** | 실시간 상태 스트리밍, STEP/STL 다운로드 |
| **JSONL 데이터셋 로그** | 파인튜닝 및 벤치마크용 실행 기록 자동 수집 |

---

## 아키텍처 개요

### 단일 LLM 파이프라인 (옵션)

```
자연어 프롬프트
      |
      v
[1] PromptBuilder  -- 시스템·사용자 프롬프트 조립
      |
      v
[2] LLMBackend     -- CadQuery 코드 생성
      |
      v
[3] _extract_code  -- 마크다운 펜스 제거
      |
      v
[4] Sandbox        -- 서브프로세스 실행 (timeout 60s)
      |
  [실패] --> [5] RepairLoop  -- LLM 유도 수정 (최대 3회)
      |
      v
[6] GeometryValidator  -- isValid / 부피 / solid 체크
      |
  [실패] --> RepairLoop (geometry-aware 프롬프트)
      |
      v
[7] Exporter       -- STEP + STL 저장
      |
      v
[8] DatasetWriter  -- JSONL 로그 기록
      |
      v
PipelineResult
```

### 멀티에이전트 파이프라인 (기본)

```
자연어 프롬프트
      |
      v
[1a] ArchitectAgent    -- 프롬프트 -> DesignPlan (JSON)
      |
      v
[1b] PatternSelector   -- DesignPlan -> 관련 패턴 선택 (LLM 없음)
      |
      v
[1c] DesignerAgent     -- plan + 패턴 -> CadQuery 코드
      |
      v
[1d] CriticAgent       -- 코드 리뷰 + 선택적 수정
      |
      v
[2~8] 동일 (Sandbox -> Validator -> RepairLoop -> Export)
```

---

## 디렉터리 구조

```
CAID_Lite/
├── config/
│   ├── default.yaml              # LLM, executor, repair, logging 설정
│   ├── patterns/                 # CAD 패턴 라이브러리 (21종 YAML)
│   │   ├── README.md
│   │   ├── plate.yaml
│   │   ├── box.yaml
│   │   └── ...
│   └── prompts/
│       ├── system_generate.txt   # 코드 생성 시스템 프롬프트
│       ├── system_repair.txt     # 수정 시스템 프롬프트
│       ├── system_architect.txt  # Architect 에이전트 프롬프트
│       └── system_critic.txt     # Critic 에이전트 프롬프트
├── gui/
│   ├── app.py                    # GUI 런처 (FastAPI + 브라우저)
│   └── static/
│       ├── index.html            # 3-pane 레이아웃
│       ├── style.css
│       └── app.js                # Three.js 씬, SSE, 채팅
├── scripts/
│   └── run_server.py             # API 서버 단독 실행
├── src/caid_lite/
│   ├── pipeline.py               # CADPipeline 오케스트레이터
│   ├── agents/
│   │   ├── base.py               # DesignPlan, CriticResult 데이터클래스
│   │   ├── architect.py          # ArchitectAgent
│   │   ├── pattern_selector.py   # PatternSelector (LLM 없음)
│   │   ├── designer.py           # DesignerAgent
│   │   └── critic.py             # CriticAgent
│   ├── llm/
│   │   ├── base.py               # LLMBackend Protocol + LLMConfig
│   │   ├── factory.py            # 공급자 -> 백엔드 팩토리
│   │   ├── prompts.py            # PromptBuilder
│   │   └── providers/
│   │       ├── qwen.py           # Qwen (DashScope, 기본값)
│   │       ├── openai_provider.py
│   │       ├── anthropic_provider.py
│   │       └── local.py          # vLLM / LM Studio / Ollama
│   ├── executor/
│   │   ├── sandbox.py            # 서브프로세스 샌드박스
│   │   ├── result.py             # ExecutionResult 데이터클래스
│   │   └── runner_template.py    # 실행 래퍼 템플릿
│   ├── validator/
│   │   └── geometry.py           # GeometryValidator
│   ├── repair/
│   │   └── loop.py               # RepairLoop
│   ├── api/
│   │   ├── server.py             # FastAPI 앱 팩토리
│   │   └── routes/
│   │       ├── chat.py           # POST /api/chat
│   │       ├── parts.py          # GET/DELETE /api/parts
│   │       ├── workspace.py      # GET /api/parts/{id}/stl|step
│   │       └── events.py         # GET /api/events (SSE)
│   ├── session/
│   │   ├── models.py             # PartEntry, ChatMessage, SessionState
│   │   └── manager.py            # SessionManager (비동기 파이프라인 디스패치)
│   └── logging/
│       ├── logger.py             # Rich 콘솔 로거
│       └── dataset.py            # JSONL 데이터셋 라이터
├── tests/
│   ├── unit/                     # API 키·CadQuery 불필요 (203개)
│   ├── integration/              # 실제 CadQuery 필요
│   └── fixtures/
│       ├── mock_llm.py           # MockLLMBackend
│       └── mock_sandbox.py       # MockSandbox
├── .env.example
├── pyproject.toml
└── README.md
```

---

## 설치

### 요구사항

- Python 3.11 이상
- `cadquery` — 선택적 의존성 (실제 실행 시 필요)

### 기본 설치 (cadquery 제외)

```bash
git clone https://github.com/jangjun7091/CAID_Lite.git
cd CAID_Lite
pip install -e .
```

### CadQuery 포함 전체 설치

```bash
pip install -e ".[cadquery]"
```

> CadQuery는 conda 환경에서 설치가 가장 안정적입니다.
> ```bash
> conda install -c conda-forge cadquery
> ```

### 개발 의존성 포함

```bash
pip install -e ".[dev]"
```

---

## 빠른 시작

### 1. 환경 설정

```bash
cp .env.example .env
# .env 파일을 열어 API 키 입력
```

`.env` 예시:

```env
LLM_PROVIDER=qwen
LLM_MODEL=qwen3-coder-480b-a35b-instruct

QWEN_API_BASE=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
QWEN_API_KEY=sk-xxxxxxxxxxxxxxxxxxxx
```

### 2. GUI 실행 (브라우저 자동 오픈)

```bash
python gui/app.py
```

브라우저에서 `http://localhost:8000` 이 자동으로 열립니다.
채팅 패널에 프롬프트를 입력하면 3D 모델이 생성됩니다.

### 3. API 서버만 실행

```bash
python scripts/run_server.py
```

```bash
# 채팅 요청 예시
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "50x40x8mm 마운팅 플레이트, 모서리에 M4 홀 4개"}'
```

---

## LLM 공급자 설정

`config/default.yaml` 또는 환경 변수로 공급자를 선택합니다.
환경 변수가 YAML 설정보다 우선 적용됩니다.

| 공급자 | `LLM_PROVIDER` 값 | 필요 환경 변수 |
|---|---|---|
| Qwen (기본) | `qwen` | `QWEN_API_KEY`, `QWEN_API_BASE` |
| OpenAI | `openai` | `OPENAI_API_KEY` |
| Anthropic | `anthropic` | `ANTHROPIC_API_KEY` |
| 로컬 서버 | `local` | `LOCAL_API_BASE`, `LOCAL_API_KEY` |

### Qwen 엔드포인트

```env
# 국제 (중국 외 지역)
QWEN_API_BASE=https://dashscope-intl.aliyuncs.com/compatible-mode/v1

# 중국 내륙
QWEN_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
```

### 공급자 전환 예시

```bash
# OpenAI 사용
LLM_PROVIDER=openai LLM_MODEL=gpt-4o python gui/app.py

# 로컬 Ollama 사용
LLM_PROVIDER=local LOCAL_API_BASE=http://localhost:11434/v1 \
  LLM_MODEL=qwen2.5-coder:32b python gui/app.py
```

---

## 파이프라인 상세

### 생성 코드 계약

LLM이 생성하는 모든 CadQuery 스크립트는 반드시:

1. `import cadquery as cq` 로 시작
2. 인자 없는 `build_model()` 함수를 정의하고 `cq.Workplane` 반환
3. `cq.exporters`, 파일 I/O, `print()` 미사용

```python
# 올바른 예시
import cadquery as cq

def build_model():
    width, height, thickness = 50.0, 40.0, 8.0
    hole_d = 4.5
    margin = 7.0
    cx, cy = width / 2 - margin, height / 2 - margin

    return (
        cq.Workplane("XY")
        .box(width, height, thickness)
        .faces(">Z").workplane()
        .pushPoints([(cx, cy), (-cx, cy), (cx, -cy), (-cx, -cy)])
        .hole(hole_d)
    )
```

### 홀 배치 규칙

| 상황 | 권장 방법 |
|---|---|
| 명시적 위치 홀 | `.faces(">Z").workplane().pushPoints([...]).hole(d)` |
| 균일 격자 홀 | `.faces(">Z").workplane().rarray(xs, ys, nx, ny).hole(d)` |
| **금지** | `.eachpoint(lambda loc: cq.Workplane(loc).circle(...), ...)` |

### `config/default.yaml` 주요 설정

```yaml
llm:
  provider: "qwen"
  model: "qwen3-coder-30b-a3b-instruct"
  temperature: 0.2
  max_tokens: 4096

executor:
  timeout_s: 60          # 서브프로세스 타임아웃

repair:
  max_repair_attempts: 3 # 자동 수정 최대 횟수

exporter:
  output_dir: "outputs"
```

---

## 멀티에이전트 모드

`CADPipeline`에 4개 에이전트를 모두 주입하면 멀티에이전트 경로가 활성화됩니다.
하나라도 없으면 단일 LLM 경로로 폴백합니다 (기존 동작 유지).

```python
from caid_lite.pipeline import CADPipeline
from caid_lite.llm.factory import LLMFactory
from caid_lite.agents import (
    ArchitectAgent, PatternSelector, DesignerAgent, CriticAgent
)

llm = LLMFactory.from_yaml(...)

pipeline = CADPipeline(
    llm=llm,
    architect=ArchitectAgent(llm=llm),
    pattern_selector=PatternSelector(),          # LLM 없음
    designer=DesignerAgent(llm=llm),
    critic=CriticAgent(llm=llm),
)

result = pipeline.run("50x40mm 마운팅 브라켓, 모서리 M4 홀 4개")
print(result.design_plan)   # Architect 출력
print(result.critic)        # Critic 평가 결과
```

### 에이전트별 역할

| 에이전트 | 입력 | 출력 | LLM 호출 |
|---|---|---|---|
| `ArchitectAgent` | 자연어 프롬프트 | `DesignPlan` (JSON) | 1회 |
| `PatternSelector` | `DesignPlan` | 관련 패턴 목록 (최대 3개) | 없음 |
| `DesignerAgent` | 프롬프트 + plan + 패턴 | CadQuery 코드 문자열 | 1회 |
| `CriticAgent` | 프롬프트 + plan + 코드 | `CriticResult` (승인/수정) | 1회 |

---

## CAD 패턴 라이브러리

`config/patterns/` 에 21종의 YAML 패턴 파일이 포함되어 있습니다.
각 파일은 선호 CadQuery 관용구, 안티패턴, 파라미터, 예제 코드, 수정 힌트를 담고 있습니다.

### 솔리드 프리미티브

| 패턴 | 용도 |
|---|---|
| `plate` | 평면 직사각형 슬랩 — 브라켓·패널 기본 바디 |
| `box` | 솔리드 또는 중공 직사각형 인클로저 |
| `cylinder` | 샤프트·핀·보스용 솔리드 실린더 |
| `tube` | 동심 관통 보어를 가진 중공 실린더 |

### 컷·홀 피처

| 패턴 | 용도 |
|---|---|
| `through_hole` | 전체 깊이 관통 원형 홀 |
| `blind_hole` | 지정 깊이에서 종료되는 원형 홀 |
| `slot` | 장방형 라운드/직사각 슬롯 컷 |
| `pocket` | 평면 바닥 직사각 리세스 |
| `hole_pushpoints` | 명시적 (x, y) 위치 다중 홀 |
| `hole_rarray` | 균일 직사각 격자 홀 |

### 돌출·엣지 피처

| 패턴 | 용도 |
|---|---|
| `boss` | 면 위 돌출 원통 보스 |
| `fillet` | 라운드 엣지 처리 |
| `chamfer` | 45도 엣지 챔퍼 |

### 기계 조립품

| 패턴 | 용도 |
|---|---|
| `l_bracket` | 직각 구조 브라켓 |
| `mounting_block` | 볼트 홀이 있는 마운팅 블록 |
| `bearing_mount` | 구름 베어링용 원통 하우징 |
| `flange` | 중앙 보어 + 균등 간격 볼트 원형 배열 플랜지 |
| `spacer` | 패스너 클리어런스 보어가 있는 단거리 스탠드오프 |
| `shaft_support` | 샤프트 정렬·지지용 보스가 있는 베이스 플레이트 |
| `connector_block` | 커넥터 포켓 + 마운팅 홀 블록 |
| `heat_sink` | 방열 핀 배열이 있는 알루미늄 히트싱크 베이스 |

---

## GUI

브라우저 기반 3-pane 인터페이스:

```
+------------------+---------------------------+-------------------+
|   Parts Shelf    |     3D Workspace          |   AI Chat Panel   |
|  (왼쪽)          |     (가운데)               |  (오른쪽)          |
|                  |                           |                   |
| v bracket_v1     |  [Three.js STL 뷰어]      | 사용자: 박스 만들어 |
| v enclosure_v2   |  [OrbitControls]          |                   |
|                  |                           | AI: 코드 생성중...  |
| [+ New Part]     |  [STEP 다운로드]           | [전송]             |
+------------------+---------------------------+-------------------+
```

- **Parts Shelf**: 생성된 파트 목록, 상태 배지(generating / validating / repairing / ready / failed)
- **3D Workspace**: Three.js r0.160.0 STL 로더, OrbitControls, 자동 카메라 피팅
- **AI Chat**: 프롬프트 입력, SSE 실시간 상태 업데이트

```bash
python gui/app.py              # 기본 (브라우저 자동 오픈)
python gui/app.py --no-browser # 브라우저 없이 서버만
python gui/app.py --port 9000  # 포트 변경
```

---

## API 서버

| 메서드 | 경로 | 설명 |
|---|---|---|
| `POST` | `/api/chat` | 프롬프트 전송, 비동기 생성 시작 |
| `GET` | `/api/parts` | 파트 목록 조회 |
| `GET` | `/api/parts/{id}` | 단일 파트 조회 |
| `DELETE` | `/api/parts/{id}` | 파트 삭제 |
| `GET` | `/api/parts/{id}/stl` | STL 파일 서빙 (3D 뷰어용) |
| `GET` | `/api/parts/{id}/step` | STEP 파일 다운로드 |
| `GET` | `/api/events` | SSE 실시간 이벤트 스트림 |

### SSE 이벤트 타입

| 이벤트 | 페이로드 | 발생 시점 |
|---|---|---|
| `part.status_changed` | `{id, status}` | 파이프라인 단계 전환마다 |
| `part.ready` | `PartEntry` (전체) | 파이프라인 성공 완료 |
| `part.failed` | `{id, errors}` | 수정 시도 소진 후 실패 |

---

## 테스트

```bash
# 단위 테스트 (API 키 및 CadQuery 불필요)
pytest tests/unit/

# 통합 테스트 (실제 CadQuery 필요)
pytest tests/integration/

# 커버리지 포함
pytest tests/unit/ --cov=caid_lite --cov-report=term-missing
```

현재 단위 테스트: **203개** (MockLLMBackend + MockSandbox 사용, 오프라인 실행 가능)

### MockLLMBackend 사용 예시

```python
from tests.fixtures.mock_llm import MockLLMBackend
from caid_lite.pipeline import CADPipeline

CODE = """
```python
import cadquery as cq

def build_model():
    return cq.Workplane("XY").box(50, 40, 8)
```
"""

def test_pipeline():
    llm = MockLLMBackend(responses=[CODE])
    pipeline = CADPipeline(llm=llm)
    result = pipeline.run("a mounting plate")
    assert result.success
```

---

## 데이터셋 로그

파이프라인 실행마다 `data/logs/runs_YYYY-MM-DD.jsonl` 에 레코드가 추가됩니다.

```json
{
  "run_id": "a3f2c8...",
  "timestamp": "2026-04-04T12:30:00Z",
  "prompt": "50x40mm 마운팅 브라켓, M4 홀 4개",
  "model": "qwen3-coder-480b-a35b-instruct",
  "generated_code": "import cadquery as cq\n...",
  "repair_iterations": 0,
  "validation": {
    "valid": true,
    "volume": 14432.0,
    "bbox": [50.0, 40.0, 8.0],
    "face_count": 10,
    "errors": []
  },
  "exports": {
    "step": "outputs/a3f2c8.../output.step",
    "stl": "outputs/a3f2c8.../output.stl"
  },
  "success": true,
  "elapsed_s": 6.8
}
```

성공 레코드(`success: true`)는 Qwen3-Coder 파인튜닝 데이터로 활용할 수 있습니다.

---

## 라이선스
MIT
연구 목적 프로젝트입니다. 라이선스는 추후 명시 예정입니다.
