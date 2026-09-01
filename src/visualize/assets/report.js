/* 그림 한 장을 그리고, 그 위에서 "고쳤다고 치면" 을 돌린다.
 *
 * 코드가 두 갈래로 갈려 있고 그 경계가 이 파일의 규칙이다.
 *
 *   renderTree()  배치를 다시 만든다. 접기/필터처럼 **구조**가 바뀔 때만 부른다.
 *   paint()       클래스만 바꾼다. 호버와 시뮬레이션처럼 **상태**가 바뀔 때 부른다.
 *
 * 시뮬레이션이 paint() 쪽에 있는 것이 §8 이 요구한 것이다. 오염원을 고쳤다고 가정해도
 * 노드는 한 픽셀도 움직이지 않고 색만 바뀐다. 그래야 수정 전후 두 장을 겹쳐 놓고
 * 오염이 위로 걷히는 과정을 읽을 수 있다.
 */
(function () {
  "use strict";

  var DATA = JSON.parse(document.getElementById("payload").textContent);
  var NODES = DATA.nodes;
  var ENTRY = DATA.entry;
  var IMPURE = [];
  for (var i = 0; i < NODES.length; i++) {
    if (NODES[i].state === "impure") IMPURE.push(i);
  }
  // 오염도 내림차순 = 작업 순서(§7). 동점은 이름으로 못박아 순서를 재현 가능하게 둔다.
  IMPURE.sort(function (a, b) {
    return NODES[b].degree - NODES[a].degree || (NODES[a].name < NODES[b].name ? -1 : 1);
  });

  var SVG = "http://www.w3.org/2000/svg";
  var LAYER = 76;   // 층 간격. 깊이는 수직으로 고정된다(§4).
  var GAP = 16;
  var PAD = 11;
  var H = 26;
  var H_IMPURE = 32;
  var FONT = '12px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace';
  var FONT_IMPURE = '600 13px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace';
  var FONT_PILL = '11px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace';

  var el = {
    stage: document.getElementById("stage"),
    viewport: document.getElementById("viewport"),
    edges: document.getElementById("edges"),
    nodes: document.getElementById("nodes"),
    tooltip: document.getElementById("tooltip"),
    rank: document.getElementById("rank"),
    rankCount: document.getElementById("rank-count"),
    sim: document.getElementById("sim"),
    counts: document.getElementById("counts"),
    entryName: document.getElementById("entry-name"),
    entryState: document.getElementById("entry-state"),
    notes: document.getElementById("notes"),
    meta: document.getElementById("meta"),
    pathOnly: document.getElementById("path-only")
  };

  /* ------------------------------------------------------------ 역방향 도달 */

  /* 오염은 호출 간선을 거꾸로 타고 올라간다. 배치용 트리가 아니라 **모든** 호출
   * 간선을 따라가야 오염도 숫자가 판정 결과와 맞는다. */
  function ancestorsOf(start) {
    var seen = {};
    seen[start] = true;
    var queue = [start];
    var out = [start];
    while (queue.length) {
      var callers = NODES[queue.pop()].callers;
      for (var i = 0; i < callers.length; i++) {
        if (!seen[callers[i]]) {
          seen[callers[i]] = true;
          out.push(callers[i]);
          queue.push(callers[i]);
        }
      }
    }
    return out;
  }

  var ANCESTORS = {};       // 오염원 id -> 그 오염원 때문에 오염된 노드(자기 포함)
  var ANCESTOR_SET = {};    // 같은 것을 조회용으로. 회수량 계산이 이 조회에 걸린다.
  var MAX_DEGREE = 1;
  IMPURE.forEach(function (id) {
    ANCESTORS[id] = ancestorsOf(id);
    ANCESTOR_SET[id] = {};
    ANCESTORS[id].forEach(function (up) { ANCESTOR_SET[id][up] = true; });
    MAX_DEGREE = Math.max(MAX_DEGREE, NODES[id].degree);
  });

  /* --------------------------------------------------------------- 화면 상태 */

  var collapsed = defaultCollapsed();
  var fixed = {};        // 고쳤다고 가정한 오염원
  var fixedCount = 0;
  var focus = null;      // 하이라이트 중인 오염원 (그래프/목록 공용)
  var view = { x: 0, y: 0, k: 1 };
  var items = {};        // id -> 배치 결과
  var nodeEls = {};
  var edgeEls = [];
  var rankRows = {};

  /* 깨끗한 서브트리는 이미 결론이 난 영역이라 펼쳐 둘 이유가 없다(§5).
   * 기준은 페이로드에 박혀 온 `impure_below` — 서브트리 안의 오염원 수다. 화면에서
   * 고쳤다고 가정해도 이 수는 다시 계산하지 않는다. 시뮬레이션이 배치를 건드리면
   * 수정 전후를 겹쳐 볼 수 없기 때문이다(§8). */
  function defaultCollapsed() {
    var set = {};
    for (var id = 0; id < NODES.length; id++) {
      if (id !== ENTRY && NODES[id].impure_below === 0 && NODES[id].children.length) {
        set[id] = true;
      }
    }
    return set;
  }

  /* ------------------------------------------------------------------- 라벨 */

  var measurer = document.createElement("canvas").getContext("2d");

  function fontOf(id) {
    return NODES[id].state === "impure" ? FONT_IMPURE : FONT;
  }

  /* 노드 안에는 짧은 이름과 오염도 숫자만 넣는다(§9). 파일 경로도 접근 목록도
   * 툴팁으로 내린다. */
  function partsOf(id) {
    var n = NODES[id];
    var parts = [{ cls: "lbl", text: n.short }];
    if (n.state === "impure") parts.push({ cls: "deg", text: " " + n.degree });
    if (collapsed[id] && n.subtree) parts.push({ cls: "badge", text: "  ▸" + n.subtree });
    if (n.unresolved) parts.push({ cls: "mark", text: " ⚠" });
    if (n.declaration) parts.push({ cls: "mark", text: " ?" });
    return parts;
  }

  function widthOf(text, font) {
    measurer.font = font;
    return Math.max(48, Math.ceil(measurer.measureText(text).width) + PAD * 2);
  }

  /* -------------------------------------------------------------- 배치 (§4) */

  /* 보이는 것만으로 트리를 다시 세운다. 자식 순서는 페이로드가 이름으로 못박아
   * 두었으므로 여기서 다시 정렬하지 않는다(§8). */
  function build(id) {
    var n = NODES[id];
    var parts = partsOf(id);
    var text = parts.map(function (p) { return p.text; }).join("");
    var item = {
      id: id,
      parts: parts,
      w: widthOf(text, fontOf(id)),
      h: n.state === "impure" ? H_IMPURE : H,
      y: n.depth * LAYER,
      kids: []
    };
    if (collapsed[id]) return item;

    var hidden = [];
    var hiddenCount = 0;
    for (var i = 0; i < n.children.length; i++) {
      var kid = n.children[i];
      // "그래도 클 때" 의 처방(§5) — 오염 경로 위의 노드만 남긴다. 지워버리는 게
      // 아니라 몇 개가 빠졌는지는 부모 밑에 남긴다.
      if (el.pathOnly.checked && NODES[kid].impure_below === 0) {
        hidden.push(kid);
        hiddenCount += 1 + NODES[kid].subtree;
        continue;
      }
      item.kids.push(build(kid));
    }
    if (hidden.length) {
      var label = "깨끗함 " + hiddenCount;
      item.kids.push({
        pill: true,
        roots: hidden,
        text: label,
        w: widthOf(label, FONT_PILL),
        h: 20,
        y: (n.depth + 1) * LAYER,
        kids: []
      });
    }
    return item;
  }

  function measureItem(item) {
    if (!item.kids.length) {
      item.span = item.w;
      return;
    }
    var span = 0;
    for (var i = 0; i < item.kids.length; i++) {
      measureItem(item.kids[i]);
      span += item.kids[i].span + (i ? GAP : 0);
    }
    item.kidsSpan = span;
    item.span = Math.max(item.w, span);
  }

  function place(item, left) {
    if (!item.kids.length) {
      item.cx = left + item.span / 2;
      return;
    }
    var x = left + (item.span - item.kidsSpan) / 2;
    for (var i = 0; i < item.kids.length; i++) {
      place(item.kids[i], x);
      x += item.kids[i].span + GAP;
    }
    var first = item.kids[0].cx;
    var last = item.kids[item.kids.length - 1].cx;
    // 부모는 자식 무리의 한가운데. 자기 폭이 자식 폭보다 넓으면 밖으로 나가지
    // 않게만 붙든다.
    item.cx = Math.min(
      Math.max((first + last) / 2, left + item.w / 2),
      left + item.span - item.w / 2
    );
  }

  /* ------------------------------------------------------------------ 그리기 */

  function svg(name, attrs) {
    var node = document.createElementNS(SVG, name);
    for (var key in attrs) node.setAttribute(key, attrs[key]);
    return node;
  }

  function link(x1, y1, x2, y2) {
    var dy = Math.max(18, (y2 - y1) / 2);
    return "M" + x1 + "," + y1 + "C" + x1 + "," + (y1 + dy) +
      " " + x2 + "," + (y2 - dy) + " " + x2 + "," + y2;
  }

  function renderTree() {
    var root = build(ENTRY);
    measureItem(root);
    place(root, 0);

    items = {};
    nodeEls = {};
    edgeEls = [];
    el.edges.textContent = "";
    el.nodes.textContent = "";

    var flat = [];
    (function walk(item) {
      flat.push(item);
      if (!item.pill) items[item.id] = item;
      item.kids.forEach(walk);
    })(root);

    // 배치 트리의 간선. 부모 아래에서 자식 위로 내려간다.
    flat.forEach(function (item) {
      item.kids.forEach(function (kid) {
        var path = svg("path", {
          d: link(item.cx, item.y + item.h, kid.cx, kid.y),
          class: "edge"
        });
        el.edges.appendChild(path);
        if (!kid.pill) edgeEls.push({ node: path, from: item.id, to: kid.id });
      });
    });

    // 배치 트리에 없는 호출 간선. 페이로드가 이미 오염 전파에 관계된 것만
    // 남겨두었다(§10) — 전부 그리면 선이 엉켜 경로를 못 따라간다.
    DATA.cross.forEach(function (edge) {
      var from = items[edge[0]];
      var to = items[edge[1]];
      if (!from || !to) return;
      var path = svg("path", {
        d: link(from.cx, from.y + from.h, to.cx, to.y),
        class: "edge cross"
      });
      el.edges.appendChild(path);
      edgeEls.push({ node: path, from: edge[0], to: edge[1], cross: true });
    });

    flat.forEach(function (item) {
      if (item.pill) {
        el.nodes.appendChild(pillElement(item));
      } else {
        el.nodes.appendChild(nodeElement(item));
      }
    });

    paint();
  }

  function nodeElement(item) {
    var group = svg("g", { transform: "translate(" + item.cx + "," + item.y + ")" });
    var n = NODES[item.id];
    var rect = svg("rect", {
      x: -item.w / 2, y: 0, width: item.w, height: item.h, rx: 4
    });
    // 오염도를 테두리 두께로도 싣는다(§2 — 크기 또는 테두리). 숫자를 읽기 전에
    // 어느 오염원이 더 넓게 퍼졌는지 눈으로 먼저 잡히게 하는 몫이다.
    if (n.state === "impure") {
      rect.setAttribute("stroke-width", (1 + 3 * (n.degree / MAX_DEGREE)).toFixed(2));
    }
    group.appendChild(rect);

    var text = svg("text", { x: 0, y: item.h / 2, "text-anchor": "middle",
      "dominant-baseline": "central" });
    item.parts.forEach(function (part) {
      var span = svg("tspan", { class: part.cls });
      span.textContent = part.text;
      text.appendChild(span);
    });
    group.appendChild(text);

    group.addEventListener("click", function (event) { onNodeClick(item.id, event); });
    group.addEventListener("mouseenter", function (event) {
      onEnter(item.id);
      moveTooltip(event);
    });
    group.addEventListener("mousemove", function (event) { moveTooltip(event); });
    group.addEventListener("mouseleave", onLeave);

    nodeEls[item.id] = group;
    return group;
  }

  function pillElement(item) {
    var group = svg("g", {
      class: "pill",
      transform: "translate(" + item.cx + "," + item.y + ")"
    });
    group.appendChild(svg("rect", {
      x: -item.w / 2, y: 0, width: item.w, height: item.h, rx: 10
    }));
    var text = svg("text", { x: 0, y: item.h / 2, "text-anchor": "middle",
      "dominant-baseline": "central" });
    text.textContent = item.text;
    group.appendChild(text);
    group.addEventListener("mouseenter", function () {
      showTooltip("<b>숨긴 깨끗한 서브트리</b><div class='t-line'>" +
        item.roots.map(function (id) { return escapeHtml(NODES[id].name); }).join(", ") +
        "</div>");
    });
    group.addEventListener("mousemove", moveTooltip);
    group.addEventListener("mouseleave", onLeave);
    return group;
  }

  /* --------------------------------------------------- 시뮬레이션 (§6) */

  /* 고쳤다고 가정한 오염원을 빼고 상태를 다시 계산한다.
   *
   * 단순 도달 수만 보면 "이걸 고치면 몇 개가 깨끗해지는가" 에 답할 수 없다. 어떤
   * 조상이 다른 오염원 때문에도 오염되어 있으면 이걸 고쳐도 그대로이기 때문이다.
   * 여기서는 실제로 깨끗해지는 노드만 색이 바뀌므로 진짜 회수량이 그대로 드러난다. */
  function simulate() {
    var active = IMPURE.filter(function (id) { return !fixed[id]; });
    var activeSet = {};
    var contaminated = {};
    active.forEach(function (id) { activeSet[id] = true; });
    active.forEach(function (id) {
      ANCESTORS[id].forEach(function (up) {
        if (up !== id) contaminated[up] = true;
      });
    });
    return {
      active: active,
      stateOf: function (id) {
        if (activeSet[id]) return "impure";
        if (contaminated[id]) return "contaminated";
        return "clean";
      }
    };
  }

  /* 지금 선택에 이 오염원을 하나 더 얹으면 추가로 깨끗해지는 노드 수. 다른
   * 오염원도 물들이고 있는 조상은 빠진다. */
  function marginal(id, active) {
    var count = 0;
    ANCESTORS[id].forEach(function (up) {
      for (var i = 0; i < active.length; i++) {
        if (active[i] !== id && ANCESTOR_SET[active[i]][up]) return;
      }
      count++;
    });
    return count;
  }

  function paint() {
    var sim = simulate();
    var hot = {};
    if (focus !== null) ANCESTORS[focus].forEach(function (id) { hot[id] = true; });

    var recovered = 0;
    for (var id = 0; id < NODES.length; id++) {
      var now = sim.stateOf(id);
      if (NODES[id].state !== "clean" && now === "clean") recovered++;
      var group = nodeEls[id];
      if (!group) continue;
      var cls = ["node"];
      if (now === "impure") cls.push("s-impure");
      else if (now === "contaminated") cls.push("s-cont");
      else if (NODES[id].state !== "clean") cls.push("s-recovered");
      else if (NODES[id].boundary) cls.push("s-boundary");
      else cls.push("s-clean");
      if (fixed[id]) cls.push("picked");
      if (hot[id]) cls.push("hot");
      if (id === ENTRY) cls.push("entry");
      group.setAttribute("class", cls.join(" "));
    }

    edgeEls.forEach(function (edge) {
      var cls = ["edge"];
      if (edge.cross) cls.push("cross");
      // 오염이 실제로 타고 올라오는 간선만 진하게. 시뮬레이션으로 아래가
      // 깨끗해지면 이 선도 같이 흐려진다.
      if (sim.stateOf(edge.to) !== "clean") cls.push("prop");
      if (hot[edge.from] && hot[edge.to]) cls.push("hot");
      edge.node.setAttribute("class", cls.join(" "));
    });

    el.stage.classList.toggle("hovering", focus !== null);
    paintRank(sim);
    paintStatus(sim, recovered);
  }

  /* ------------------------------------------------------------- 순위표 (§7) */

  /* 그래프는 모양을 보여주고 목록은 순서를 보여준다. 목록 그대로가 작업 순서다. */
  function renderRank() {
    el.rankCount.textContent = IMPURE.length;
    if (!IMPURE.length) {
      el.rank.innerHTML = "<li class='muted' style='grid-template-columns:1fr'>" +
        "오염원이 없다. 진입점에 바로 테스트를 붙이면 된다.</li>";
      return;
    }
    IMPURE.forEach(function (id) {
      var n = NODES[id];
      var row = document.createElement("li");
      row.innerHTML =
        "<div class='r-deg'>" + n.degree + "</div><div>" +
        "<div class='r-name'>" + escapeHtml(n.name) + "</div>" +
        "<div class='r-sub'>" + escapeHtml(n.file) + ":" + n.line +
        " · 깊이 " + n.depth + " · <span class='r-gain'></span></div>" +
        "<div class='r-reasons'>" + n.reasons.map(varChip).join("") + "</div>" +
        "</div>";
      row.addEventListener("click", function () { toggleFixed(id); });
      row.addEventListener("mouseenter", function () { setFocus(id); });
      row.addEventListener("mouseleave", function () { setFocus(null); });
      el.rank.appendChild(row);
      rankRows[id] = row;
    });
  }

  function varChip(reason) {
    var access = [];
    if (reason.read) access.push("r");
    if (reason.write) access.push("w");
    if (reason.addr) access.push("&");
    var cls = "r-var" + (reason.static ? " static" : "");
    var title = reason.static ? "함수 내 static — 밖에서 리셋할 수 없다"
      : reason.unknown ? "state 에 없는 대상 — 기준을 적용할 수 없어 남았다" : "전역";
    return "<span class='" + cls + "' title='" + title + "'>" +
      escapeHtml(reason.name) +
      "<span class='acc'> " + access.join("") + "</span></span>";
  }

  function paintRank(sim) {
    IMPURE.forEach(function (id) {
      var row = rankRows[id];
      if (!row) return;
      row.className = (fixed[id] ? "picked " : "") + (focus === id ? "hot" : "");
      var gain = row.querySelector(".r-gain");
      gain.textContent = fixed[id]
        ? "고쳤다고 가정함"
        : (fixedCount ? "추가 회수 " : "단독 회수 ") + marginal(id, sim.active) + "개";
    });
  }

  /* --------------------------------------------------------------- 머리말/요약 */

  function paintStatus(sim, recovered) {
    var entryState = sim.stateOf(ENTRY);
    var chip = el.entryState;
    if (entryState === "impure") {
      chip.className = "chip bad";
      chip.textContent = "오염원";
    } else if (entryState === "contaminated") {
      chip.className = "chip warn";
      chip.textContent = "오염됨";
    } else if (NODES[ENTRY].state !== "clean") {
      chip.className = "chip sim";
      chip.textContent = "회수됨 (가정)";
    } else {
      chip.className = "chip good";
      chip.textContent = "깨끗함";
    }

    var boundaries = 0;
    for (var i = 0; i < NODES.length; i++) if (NODES[i].boundary) boundaries++;
    el.counts.innerHTML =
      "노드 <b>" + NODES.length + "</b>개 <span class='muted'>(전체 " + DATA.total + " 중)</span>" +
      "<span class='sep'>·</span>오염원 <b>" + IMPURE.length + "</b>" +
      "<span class='sep'>·</span>깨끗한 경계 <b>" + boundaries + "</b>";

    el.sim.innerHTML =
      "<div class='sim-line'>선택한 오염원 <b>" + fixedCount + "</b>개" +
      "<span class='sep'>→</span>회수되는 노드 <b>" + recovered + "</b>개</div>" +
      "<div class='sim-help'>" +
      (fixedCount
        ? "진입점은 " + (sim.stateOf(ENTRY) === "clean" ? "이 선택만으로 깨끗해진다." :
          "아직 오염되어 있다. 남은 오염원을 더 골라 본다.")
        : "오염원을 클릭하면 고쳤다고 가정하고 전체를 다시 칠한다. 여러 개를 동시에 고를 수 있다.") +
      "</div>";
    var reset = document.createElement("button");
    reset.type = "button";
    reset.textContent = "전체 되돌리기";
    reset.disabled = !fixedCount;
    reset.addEventListener("click", function () {
      fixed = {};
      fixedCount = 0;
      paint();
    });
    el.sim.appendChild(reset);
  }

  function renderNotes() {
    var declarations = [];
    var unresolved = [];
    for (var i = 0; i < NODES.length; i++) {
      if (NODES[i].declaration) declarations.push(NODES[i].name);
      if (NODES[i].unresolved) unresolved.push(NODES[i].name);
    }
    var lines = [];
    if (unresolved.length) {
      lines.push("<p>⚠ 함수 포인터로 아래를 알 수 없는 노드 " + unresolved.length +
        "개 — 이 노드와 그 조상은 경계로 쓸 수 없다.<br><span class='mono'>" +
        escapeHtml(unresolved.join(", ")) + "</span></p>");
    }
    if (declarations.length) {
      lines.push("<p>? 정의를 보지 못해 깨끗한 리프로 취급한 노드 " + declarations.length +
        "개.<br><span class='mono'>" + escapeHtml(declarations.join(", ")) + "</span></p>");
    }
    if (DATA.omitted_edges) {
      lines.push("<p>오염과 무관해 생략한 호출 간선 " + DATA.omitted_edges + "개.</p>");
    }
    el.notes.innerHTML = lines.length
      ? "<div class='notes-head'>눈으로 확인할 것</div>" + lines.join("")
      : "";

    el.meta.innerHTML =
      "<div>기준 <span class='mono'>" + escapeHtml(DATA.criteria) + "</span></div>" +
      "<div>입력 <span class='mono'>" + escapeHtml(DATA.source) + "</span></div>" +
      "<div>추출 " + escapeHtml(DATA.generated_at) + "</div>" +
      (DATA.prefix ? "<div>이름에서 <span class='mono'>" + escapeHtml(DATA.prefix) +
        "</span> 접두사를 잘라 표시한다</div>" : "");
  }

  /* ------------------------------------------------------------------ 인터랙션 */

  function onNodeClick(id, event) {
    // 화면을 끌다가 노드 위에서 손을 뗀 것은 클릭이 아니다.
    if (suppressClick) return;
    // 오염원 클릭은 시뮬레이션이다(§6). 접기는 Shift 를 눌러 따로 부른다.
    if (event.shiftKey || NODES[id].state !== "impure") {
      if (!NODES[id].children.length) return;
      if (collapsed[id]) delete collapsed[id];
      else collapsed[id] = true;
      renderTree();
      return;
    }
    toggleFixed(id);
  }

  function toggleFixed(id) {
    if (fixed[id]) {
      delete fixed[id];
      fixedCount--;
    } else {
      fixed[id] = true;
      fixedCount++;
    }
    paint();
  }

  function setFocus(id) {
    focus = id !== null && NODES[id] && NODES[id].state === "impure" ? id : null;
    paint();
  }

  function onEnter(id) {
    setFocus(id);
    var n = NODES[id];
    var lines = ["<b>" + escapeHtml(n.name) + "</b>",
      "<div class='t-line'>" + escapeHtml(n.file) + ":" + n.line +
      " · 깊이 " + n.depth + "</div>"];
    if (n.state === "impure") {
      lines.push("<div class='t-line'>오염도 " + n.degree +
        " — 이 노드 때문에 오염된 노드 수</div>");
      lines.push("<div class='t-reason'>" + n.reasons.map(function (r) {
        return escapeHtml(r.name) + (r.static ? " (static)" : "");
      }).join(", ") + "</div>");
    } else if (n.state === "contaminated") {
      lines.push("<div class='t-line'>오염됨 — 후손에 오염원이 있다. 손댈 곳은 아니다</div>");
    } else if (n.boundary) {
      lines.push("<div class='t-line'>깨끗한 서브트리 루트 — 지금 테스트를 붙일 수 있다</div>");
    }
    if (n.subtree) {
      lines.push("<div class='t-line'>서브트리 " + n.subtree + "개" +
        (collapsed[id] ? " (접힘)" : "") + "</div>");
    }
    if (n.unresolved) lines.push("<div class='t-line'>⚠ 함수 포인터 호출이 있어 아래가 불완전하다</div>");
    if (n.declaration) lines.push("<div class='t-line'>? 정의를 보지 못했다</div>");
    showTooltip(lines.join(""));
  }

  function onLeave() {
    setFocus(null);
    el.tooltip.hidden = true;
  }

  function showTooltip(html) {
    el.tooltip.innerHTML = html;
    el.tooltip.hidden = false;
  }

  function moveTooltip(event) {
    var box = el.stage.getBoundingClientRect();
    var x = event.clientX - box.left + 14;
    var y = event.clientY - box.top + 14;
    var width = el.tooltip.offsetWidth;
    var height = el.tooltip.offsetHeight;
    if (x + width > box.width) x = box.width - width - 6;
    if (y + height > box.height) y = event.clientY - box.top - height - 10;
    el.tooltip.style.left = Math.max(6, x) + "px";
    el.tooltip.style.top = Math.max(6, y) + "px";
  }

  function escapeHtml(text) {
    return String(text).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }

  /* ------------------------------------------------------------- 이동과 확대 */

  function applyView() {
    el.viewport.setAttribute("transform",
      "translate(" + view.x + "," + view.y + ") scale(" + view.k + ")");
  }

  function fit() {
    var box = el.nodes.getBBox();
    var stage = el.stage.getBoundingClientRect();
    if (!box.width || !box.height) return;
    var k = Math.min(1.2, (stage.width - 48) / box.width, (stage.height - 72) / box.height);
    view.k = Math.max(0.15, k);
    view.x = (stage.width - box.width * view.k) / 2 - box.x * view.k;
    // 층이 얕으면 세로로 남는다. 위에 붙이지 않고 가운데로 둔다.
    view.y = Math.max(24, (stage.height - box.height * view.k) / 2) - box.y * view.k;
    applyView();
  }

  el.stage.addEventListener("wheel", function (event) {
    event.preventDefault();
    var box = el.stage.getBoundingClientRect();
    var mx = event.clientX - box.left;
    var my = event.clientY - box.top;
    var k = Math.min(3, Math.max(0.15, view.k * Math.exp(-event.deltaY * 0.0015)));
    view.x = mx - (mx - view.x) * (k / view.k);
    view.y = my - (my - view.y) * (k / view.k);
    view.k = k;
    applyView();
  }, { passive: false });

  var drag = null;
  var suppressClick = false;
  el.stage.addEventListener("mousedown", function (event) {
    drag = { x: event.clientX, y: event.clientY, vx: view.x, vy: view.y, moved: false };
    el.stage.classList.add("dragging");
  });
  window.addEventListener("mousemove", function (event) {
    if (!drag) return;
    view.x = drag.vx + (event.clientX - drag.x);
    view.y = drag.vy + (event.clientY - drag.y);
    if (Math.abs(event.clientX - drag.x) + Math.abs(event.clientY - drag.y) > 3) {
      drag.moved = true;
    }
    applyView();
  });
  window.addEventListener("mouseup", function () {
    suppressClick = !!(drag && drag.moved);
    drag = null;
    el.stage.classList.remove("dragging");
  });
  // 노드의 click 핸들러가 먼저 돌고 여기로 올라온다. 한 번 막았으면 풀어 준다.
  el.stage.addEventListener("click", function () { suppressClick = false; });

  /* ---------------------------------------------------------------- 시작 */

  // 필터는 화면에 남는 것을 통째로 바꾸므로 다시 맞춘다. 반대로 접기/펼치기는
  // 보고 있던 자리를 지킨다 — 한 군데를 열어보려고 누른 것이기 때문이다.
  el.pathOnly.addEventListener("change", function () {
    renderTree();
    fit();
  });
  document.getElementById("expand-all").addEventListener("click", function () {
    collapsed = {};
    renderTree();
  });
  document.getElementById("collapse-clean").addEventListener("click", function () {
    collapsed = defaultCollapsed();
    renderTree();
  });
  document.getElementById("fit").addEventListener("click", fit);

  el.entryName.textContent = NODES[ENTRY].name;
  renderRank();
  renderNotes();
  renderTree();
  fit();
})();
