# 정적 콜트리 추출: 원칙과 스키마

레거시 C 코드베이스에서 단일 진입점의 콜트리를 기계적으로 추출하기 위한 참조 문서.
추출 도구는 **libclang + `compile_commands.json`** 으로 고정한다.

---

## 1. 왜 AST인가

바이너리(nm/objdump) 대신 AST를 선택한 근거. 도구를 바꾸고 싶을 때 이 조건들이 여전히 성립하는지부터 확인한다.

| 필요한 것 | AST | 바이너리 |
|---|---|---|
| 전역 접근 여부·방향(read/write) | `DeclRefExpr` 한 번의 순회 | relocation 역매핑 + 명령어 디코딩 |
| 최적화 영향 | 없음 (전처리 후 AST) | 인라인·테일콜로 노드 소실 |
| 매크로 뒤의 호출 | 전개 후 관측 | 구분 불가 |
| static 함수 정체성 | 파일 스코프까지 보존 | 스트립 시 소실 |

핵심은 **콜 엣지와 상태 접근을 같은 순회에서 동시에 얻는다**는 점이다. 오염원 판정에 필요한 정보가 콜 엣지가 아니라 상태 접근이므로, 이 둘이 분리되면 도구 체인이 두 배가 된다.

바이너리 분석은 "실제로 무엇이 링크되었는가"에 대해서만 우위에 있다. 조건부 컴파일로 빠진 코드를 확인할 때 크로스 체크용으로만 쓴다.

---

## 2. 추출 원칙

### 2.1 사실만 뽑는다. 판단은 하지 않는다

추출기가 기록하는 것은 관측 가능한 사실뿐이다.

- 기록한다: `g_cfg`를 47행에서 읽는다. `g_cfg`는 `const`다.
- 기록하지 않는다: `g_cfg`는 오염원이다. 이 노드의 오염도는 7이다.

오염원 판정 기준(const 제외 여부, 정적 지역변수 포함 여부, 읽기 전용 접근의 취급)은 분석을 진행하면서 계속 바뀐다. 판단을 추출기에 넣으면 기준이 바뀔 때마다 전체 재파싱이 필요하다. 판정은 별도 단계에서 이 JSON을 입력으로 받아 수행한다.

### 2.2 트리가 아니라 플랫 맵

중첩된 트리 구조로 직렬화하지 않는다.

- 공유 노드(여러 부모가 호출하는 유틸 함수)가 중복 직렬화된다
- 재귀에서 무한 전개된다
- 역방향 도달성(조상 수) 계산에 결국 플랫 맵으로 되돌려야 한다

USR을 키로 하는 단일 맵으로 두고, 트리 뷰는 렌더링 시점에 파생시킨다.

### 2.3 노드 정체성은 USR

이름으로 키를 잡으면 파일마다 존재하는 static `init()`, `reset()`이 전부 한 노드로 뭉친다. USR은 static 심볼에 파일 경로를 포함하므로 충돌하지 않는다.

```
c:@F@process_frame        // extern 함수
c:proc.c@F@init           // static 함수 — 파일 경로 포함
c:@g_cfg                  // 전역 변수
c:proc.c@g_buf            // static 전역
```

직접 문자열을 조립하지 말고 `cursor.get_usr()`이 준 값을 그대로 쓴다.

### 2.4 TU 단위 파싱 후 USR로 병합

`compile_commands.json`의 각 엔트리가 하나의 TU다. TU마다 파싱한 결과를 USR 키로 병합한다.

- 헤더의 선언과 `.c`의 정의는 USR이 같으므로 자연히 합쳐진다
- 헤더에 정의된 `inline`/`static inline` 함수는 TU마다 중복 등장하므로 dedupe 대상이다
- 병합 시 `kind`는 `definition`이 `declaration`을 덮어쓴다 (정의를 한 번이라도 봤으면 정의로 확정)

### 2.5 상태는 전역과 함수 내 static을 한 테이블에

함수 내부의 `static` 지역변수는 스코프만 좁을 뿐 숨은 상태라는 성격이 전역과 동일하다. 오염원으로서의 취급도 같다. 전역만 훑으면 이 부류가 통째로 누락된다.

그래서 필드 이름을 `global_uses`가 아니라 `state_uses`로 둔다.

---

## 3. 스키마

### 3.1 최상위 구조

```json
{
  "schema_version": 1,
  "meta": {
    "entry_point": "c:@F@process_frame",
    "compile_commands": "build/compile_commands.json",
    "clang_version": "17.0.6",
    "generated_at": "2026-08-31T10:00:00+09:00",
    "tu_count": 84
  },
  "nodes": { },
  "state": { }
}
```

### 3.2 `nodes` — 함수

키는 함수의 USR.

```json
"c:@F@process_frame": {
  "name": "process_frame",
  "linkage": "external",
  "kind": "definition",
  "loc": { "file": "src/proc.c", "line": 42 },
  "return_type": "int",
  "params": [
    { "name": "buf", "type": "uint8_t *" },
    { "name": "len", "type": "size_t" }
  ],
  "calls": [
    { "callee": "c:@F@decode", "loc": { "file": "src/proc.c", "line": 51 } },
    { "callee": "c:proc.c@F@reset", "loc": { "file": "src/proc.c", "line": 63 } }
  ],
  "state_uses": [
    { "target": "c:@g_cfg", "access": "read", "loc": { "file": "src/proc.c", "line": 47 } },
    { "target": "c:proc.c@1043@F@process_frame@retry_cnt",
      "access": "write", "loc": { "file": "src/proc.c", "line": 55 } }
  ],
  "unresolved_calls": []
}
```

| 필드 | 값 | 비고 |
|---|---|---|
| `name` | 원본 식별자 | 표시용. 키로 쓰지 않는다 |
| `linkage` | `external` \| `internal` | `internal` = `static` |
| `kind` | `definition` \| `declaration` | |
| `loc` | `{file, line}` | 정의 위치. `declaration`이면 선언 위치 |
| `return_type` | 문자열 | 시그니처 변경 계획 수립용 |
| `params` | `[{name, type}]` | 전역을 파라미터로 승격할 때 기존 시그니처 참조 |
| `calls` | `[{callee, loc}]` | 해석된 직접 호출. 같은 대상 다중 호출은 각각 기록 |
| `state_uses` | `[{target, access, loc}]` | `state` 테이블 참조 |
| `unresolved_calls` | `[{loc, expr, reason}]` | 해석 실패한 호출 |

**`kind: "declaration"` 의 의미**
정의를 어느 TU에서도 보지 못한 함수. 외부 라이브러리 호출이 여기 걸린다. 콜트리에서 **리프로 확정**되며, 내부를 알 수 없으므로 상태 접근도 알 수 없다. 분석 단계에서 별도 취급이 필요한 노드이므로 반드시 구분해서 기록한다.

**`unresolved_calls`**
함수 포인터 호출 등 콜리를 특정할 수 없는 지점.

```json
{ "loc": { "file": "src/proc.c", "line": 88 },
  "expr": "handlers[i].fn",
  "reason": "function_pointer" }
```

이 프로젝트에서는 함수 포인터가 드물지만, 빈 배열이 아닌 노드는 콜트리가 불완전하다는 신호이므로 수동 확인 대상으로 남긴다. `reason`은 `function_pointer` \| `inline_asm` \| `unknown`.

### 3.3 `state` — 전역 및 함수 내 static

키는 변수의 USR.

```json
"c:@g_cfg": {
  "name": "g_cfg",
  "type": "struct config",
  "scope": "file_global",
  "linkage": "external",
  "is_const": true,
  "loc": { "file": "src/cfg.c", "line": 10 }
},
"c:proc.c@1043@F@process_frame@retry_cnt": {
  "name": "retry_cnt",
  "type": "int",
  "scope": "function_static",
  "linkage": "internal",
  "is_const": false,
  "owner": "c:@F@process_frame",
  "loc": { "file": "src/proc.c", "line": 44 }
}
```

| 필드 | 값 | 비고 |
|---|---|---|
| `scope` | `file_global` \| `function_static` | |
| `linkage` | `external` \| `internal` | `internal` = 파일 내 `static` |
| `is_const` | bool | **필수** |
| `owner` | USR \| 없음 | `function_static`일 때 소속 함수 |

**`is_const`가 필수인 이유**
`const` 룩업 테이블, 상수 설정 구조체는 오염원이 아니다. 이 플래그가 없으면 오염도가 부풀어 우선순위가 왜곡된다. 다만 판정 자체는 분석 단계의 몫이므로, 추출기는 사실만 기록한다.

### 3.4 `access` 값

| 값 | 조건 |
|---|---|
| `read` | rvalue 문맥에서 참조 |
| `write` | 대입 좌변, 복합 대입, `++`/`--` |
| `readwrite` | 복합 대입 등 읽고 쓰는 경우 |
| `addr` | `&g_state` — 주소만 취함 |

**`addr`을 별도로 두는 이유**
주소를 넘긴 시점에서 읽기인지 쓰기인지 정적으로 판정할 수 없다. `read`로 뭉뚱그리면 실제 변경을 놓치고, `write`로 뭉뚱그리면 과잉 계상된다. 별도 값으로 남겨두고 분석 단계에서 보수적으로(= `readwrite`) 처리하거나 수동 확인한다. 배열명이 포인터로 감쇠하는 경우도 여기에 포함된다.

---

## 4. 파생 파일 (분석 단계 출력)

추출 결과를 입력으로 받아 별도 파일로 생성한다. 같은 USR을 키로 쓰므로 조인이 자명하다.

```json
{
  "schema_version": 1,
  "source": "calltree.json",
  "criteria": {
    "exclude_const": true,
    "include_function_static": true,
    "addr_as": "readwrite"
  },
  "nodes": {
    "c:@F@process_frame": {
      "is_impure": true,
      "impurity_reasons": ["c:@g_cfg"],
      "is_contaminated": false,
      "contamination_degree": 7,
      "is_clean_subtree_root": false,
      "scc_id": null
    }
  }
}
```

`criteria`를 파일에 남기는 이유는, 기준을 바꿔가며 여러 번 돌릴 때 어떤 결과가 어떤 기준에서 나왔는지 구분하기 위해서다.

---

## 5. 분석 단계에서 처리할 것 (추출기 밖)

- **재귀 / 상호 재귀**: 조상 수 계산이 무한 루프에 빠진다. SCC로 축약한 뒤 DAG에서 계산하고, `scc_id`로 원 노드를 되짚는다.
- **진입점 기준 가지치기**: `nodes`에는 TU 전체가 들어온다. 진입점에서 도달 가능한 노드만 남긴다.
- **`declaration` 리프의 취급**: 내부를 알 수 없으므로 오염 여부를 판정할 수 없다. 별도 표시 후 수동 판단.

---

## 6. 알려진 한계

**함수 내 static 변수의 USR이 불안정하다**
clang이 로컬 선언 USR에 파일 오프셋을 포함시킨다(`c:proc.c@1043@F@...`). 위쪽 코드를 한 줄만 수정해도 값이 바뀐다. 단일 시점 분석에서는 문제가 없지만, 리팩토링 전/후 스냅샷을 비교하려면 `파일::함수::변수` 형태로 정규화한 키가 필요하다. 현 단계에서는 USR을 그대로 쓴다.

**조건부 컴파일**
`compile_commands.json`에 기록된 매크로 정의 조합에서만 관측된다. 다른 빌드 구성에서 활성화되는 코드는 트리에 나타나지 않는다.

**`compile_commands.json` 생성**
CMake는 `-DCMAKE_EXPORT_COMPILE_COMMANDS=ON`, Makefile은 `bear -- make`.
