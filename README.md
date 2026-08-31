# calltree

`calltree-extraction-schema.md` 의 추출기 구현. libclang 으로 `compile_commands.json`
의 각 TU 를 훑어 **콜 엣지와 상태 접근을 같은 순회에서** 뽑고, USR 을 키로 하는
플랫 맵(`calltree.schema.json`)으로 직렬화한다.

추출기는 사실만 기록한다. 오염원 판정, 오염도 계산, 진입점 기준 가지치기는 이
결과 JSON 을 입력으로 받는 별도 단계의 몫이다.

## 구조

```
.
├── calltree-extraction-schema.md   원칙 문서 (원본)
├── calltree.schema.json            출력 계약 (원본)
├── pyproject.toml
├── src/
│   └── calltree/
│       ├── model.py                스키마에 1:1 대응하는 데이터 모델
│       ├── compile_db.py           compile_commands.json 읽기 + 드라이버 플래그 제거
│       ├── libclang_loader.py      libclang 로딩 + 버전 대조
│       ├── preflight.py            실행 전 점검 (스모크 파싱)
│       ├── extract.py              AST 순회: 콜 엣지 + 상태 접근
│       ├── merge.py                USR 병합 (정의가 선언을 덮어쓴다)
│       ├── validation.py           calltree.schema.json 검증
│       └── cli.py                  calltree extract / validate / doctor
└── tests/
    ├── conftest.py
    ├── fixtures/proj/              실제로 파싱하는 C 픽스처 프로젝트
    ├── test_model.py
    ├── test_compile_db.py
    ├── test_merge.py
    ├── test_extract.py             libclang 으로 실제 파싱해 사실을 검증
    ├── test_validation.py
    ├── test_preflight.py           어긋난 libclang 에서 멈추는지 확인
    └── test_cli.py
```

## 설치

```bash
pip install -e ".[dev]"
calltree doctor          # libclang 이 실제로 쓸 만한지 확인
```

`doctor` 가 이렇게 나오면 준비된 것이다.

```
네이티브 libclang : clang version 18.1.1
파이썬 바인딩     : libclang 18.1.1
스모크 파싱       : 통과
```

### libclang 설치

파이썬 바인딩(`clang.cindex`)과 네이티브 `libclang.so` 는 별개의 물건이고, **메이저
버전이 같아야** 한다. 두 가지 방법이 있다.

**[1] PyPI 휠 하나로 (권장).** 바인딩과 `.so` 가 한 벌로 온다.

```bash
pip uninstall -y clang          # 두 패키지는 같은 clang/ 디렉터리를 덮어쓴다
pip install 'libclang==18.1.1'
```

**[2] 시스템 clang 사용.**

```bash
apt install libclang-18-dev     # Debian/Ubuntu
dnf install clang-devel         # Fedora/RHEL
brew install llvm               # macOS

export CALLTREE_LIBCLANG_LIBRARY=/usr/lib/llvm-18/lib/libclang.so.1
export CALLTREE_LIBCLANG_LIBRARY=$(brew --prefix llvm)/lib/libclang.dylib   # macOS

pip uninstall -y libclang && pip install 'clang==18.1.8'   # .so 의 메이저에 맞춘다
```

같은 안내가 실패 메시지에도 그대로 붙어 나오므로, 막히면 에러 메시지만 보면 된다.

### 어긋나면 아예 안 돈다

버전 불일치는 두 가지로 갈리는데, 조용한 쪽이 더 위험하다.

| 상황 | 기본 동작 | 이 프로젝트 |
|---|---|---|
| 바인딩이 `.so` 보다 최신 | `undefined symbol` 로 죽음 | 시작 전에 잡고 설치법 출력, 종료 코드 2 |
| 바인딩이 `.so` 보다 구형 | **조용히 로드됨.** 새 커서 종류를 놓쳐 틀린 콜트리가 나온다 | 메이저 버전 대조로 잡고 멈춘다 |
| `clang` 과 `libclang` 이 둘 다 설치됨 | 나중에 설치된 쪽이 덮어써서 무엇이 사는지 불명 | 잡고 멈춘다 |

그래서 `extract` 는 **compile_commands.json 을 열기 전에** 점검부터 한다. 로딩과 버전
대조에 더해, 작은 C 조각을 실제로 훑어서 콜 엣지·접근 방향·`function_static` 소유자
같은 우리가 의존하는 관측이 그대로 나오는지 본다(`src/calltree/preflight.py`).
하나라도 어긋나면 아무 것도 추출하지 않고 종료 코드 2 로 멈춘다.

메이저 버전 대조만 무시하려면 `CALLTREE_ALLOW_VERSION_MISMATCH=1` 이 있지만, 조용히
틀린 결과를 받게 되므로 권하지 않는다. 스모크 파싱 실패는 무시할 수 없다.

## 사용법

```bash
# 1. compile_commands.json 확보
cmake -DCMAKE_EXPORT_COMPILE_COMMANDS=ON -B build      # 또는: bear -- make

# 2. 추출
calltree extract \
    --compile-commands build/compile_commands.json \
    --entry process_frame \
    --root . \
    --output calltree.json \
    --validate

# 3. 나중에 따로 검증 (libclang 이 필요 없다)
calltree validate calltree.json
```

종료 코드: `0` 성공, `1` 스키마 위반이나 `--strict` 실패, `2` libclang 문제로 아무
것도 하지 못함.

| 옵션 | 설명 |
|---|---|
| `--entry` | 진입점. 함수 이름 또는 USR. 이름이 여러 노드에 걸리면(파일마다 있는 static `init` 등) 후보를 보여주고 멈춘다 |
| `--root` | `loc.file` 을 상대경로로 만들 기준 디렉터리 |
| `--include-system` | 시스템 헤더의 선언까지 노드로 기록 |
| `--strict` | 파싱 에러가 하나라도 있으면 종료 코드 1 |
| `--libclang` | libclang 공유 라이브러리 경로 |

`calltree doctor` 는 점검만 하고 결과를 보여준다. `--libclang` 을 같이 줄 수 있다.

파이썬에서 직접 쓸 수도 있다.

```python
from calltree.compile_db import load_compile_commands
from calltree.extract import extract

result = extract(load_compile_commands("build/compile_commands.json"), root=".")
node = result.nodes["c:@F@process_frame"]
print([call.callee for call in node.calls])
print([(use.target, use.access) for use in node.state_uses])
```

## 스펙에서 애매했던 지점의 구현 판단

문서가 두 가지로 읽히는 곳은 다음과 같이 정했다. 판정 기준이 아니라 관측 방식에
대한 결정이므로 추출기 안에 들어가 있다.

- **복합 대입은 `readwrite`.** `access` 표에서 `write` 와 `readwrite` 양쪽에 걸쳐
  있는데, `g_flag += v` 는 읽고 쓰므로 정보량이 많은 쪽을 남긴다. `++`/`--` 도 같다.
  순수한 `=` 좌변만 `write` 다.
- **배열명의 감쇠는 `addr`.** `sink(g_buf)` 는 주소를 넘긴 것이므로 방향을 알 수
  없다. 다만 `g_buf[i]` 처럼 첨자를 거친 접근은 감쇠가 아니라 실제 원소 접근이므로
  `read`/`write` 로 기록한다.
- **tentative definition 은 정의로 친다.** `int g_flag;` 는 libclang 의
  `is_definition()` 이 False 지만, 헤더의 `extern int g_flag;` 보다는 이쪽이 정의에
  가까우므로 `loc` 이 `.c` 를 가리키게 한다.
- **시스템 헤더 선언은 기본적으로 노드로 만들지 않는다.** 단, 코드가 실제로 호출한
  함수는 `calls` 의 참조가 끊기지 않도록 `declaration` 노드로 반드시 넣는다.
- **`inline_asm`** 은 함수 본문에서 asm 문을 만나면 `unresolved_calls` 에 기록한다.
  콜리를 특정할 수 없는 지점이라는 점에서 함수 포인터와 성격이 같다.

## 알려진 한계

원본 문서 §6 에 더해:

- **함수 주소 취득은 콜 엣지가 아니다.** `handlers[i].fn = reset;` 처럼 함수를
  호출하지 않고 참조만 하는 지점은 기록하지 않는다. 그 함수가 실제로 불리는 곳은
  `unresolved_calls` 의 `function_pointer` 로 남으므로, 둘을 잇는 것은 수동 확인
  대상이다.
- **함수 내 static 의 USR 이 불안정하다.** clang 이 파일 오프셋을 넣기 때문에
  (`c:proc.c@264@F@process_frame@retry_cnt`) 리팩토링 전후 스냅샷 비교에는 정규화한
  키가 따로 필요하다.
- **조건부 컴파일.** `compile_commands.json` 에 기록된 매크로 조합에서 관측된 것만
  나온다.

## 테스트

```bash
pytest
```

`tests/fixtures/proj` 를 실제로 libclang 으로 파싱해서 검증한다. 같은 이름의 static
함수가 뭉치지 않는지, 헤더의 `static inline` 이 TU 마다 중복되지 않는지, 접근
방향이 문맥대로 나오는지, 출력이 스키마를 만족하는지를 본다.

libclang 이 어긋나 있으면 **테스트를 하나도 돌리지 않는다.** 수집 전에 점검해서
설치법과 함께 통째로 실패한다(종료 코드 4).

```console
$ pytest
ERROR:
네이티브 libclang 을 열 수 없다: ... undefined symbol: clang_annotateTokens
설치 방법
─────────
...
```

건너뛰기로 두면 CI 는 초록불인데 파싱 테스트는 한 개도 안 돈 상태가 되므로, 그
모양새를 만들지 않는다.
