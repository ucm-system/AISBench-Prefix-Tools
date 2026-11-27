
#!/usr/bin/env python3
"""KV Cache命中过程动画: 为单次测试报告生成自包含的交互式Canvas动画章节。

动画基于AISBench prefix测试的两阶段原理:
1. 预埋阶段: 先以 request rate = 0 执行 prefill 数据集, 把各请求可复用前缀的
   KV cache 写入推理系统缓存(先填HBM显存, HBM占满后溢出写入外置存储/DRAM分级缓存)。
2. 正式测试阶段: 发送带 repeat_rate 前缀比例的请求, 先查询HBM; 未命中转查外置存储,
   命中则把KV cache加载回HBM用于forward阶段attention计算; 仍未命中由prefill重算。
"""

import html
import json
from typing import Dict, List, Optional


def _fmt_len(value) -> str:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value or "")
    if num >= 1024 * 1024 and num % (1024 * 1024) == 0:
        return f"{int(num // (1024 * 1024))}M"
    if num >= 1024 and num % 1024 == 0:
        return f"{int(num // 1024)}K"
    return str(int(num)) if num == int(num) else str(num)


def _to_float(value) -> Optional[float]:
    """宽容地把日志/CSV中的数值字段转为float(支持千分位逗号)。"""
    try:
        if value in (None, ""):
            return None
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _to_int(value) -> int:
    num = _to_float(value)
    return int(num) if num is not None else 0


def _cache_frac(value: Optional[float]) -> Optional[float]:
    """把百分数命中率转为0~1小数并限幅。"""
    if value is None:
        return None
    return max(0.0, min(100.0, value)) / 100.0


def _hit_rate_text(frac: Optional[float]) -> str:
    return "未解析到" if frac is None else f"{frac * 100:.1f}%"


def _repeat_text(repeat: Optional[float]) -> str:
    return "未提供" if repeat is None else f"{repeat * 100:.0f}%"


def _scenario_text(hbm: Optional[float], external: Optional[float],
                   repeat: Optional[float]) -> str:
    """按prefix测试两阶段原理描述该用例KV cache的命中过程。"""
    hbm = _cache_frac(hbm)
    external = _cache_frac(external)
    repeat_text = _repeat_text(repeat)
    parts: List[str] = []

    if hbm is None:
        parts.append("本用例日志中未解析到 HBM 命中率，动画按 0% 演示。")
    elif hbm > 0:
        parts.append(
            f"HBM 命中率为 {hbm * 100:.1f}%：预埋阶段写入 HBM 的前缀 KV cache 在正式测试阶段"
            f"仍有一部分留在 HBM 中，带前缀（repeat_rate = {repeat_text}）的请求直接在 HBM 中"
            "命中这部分前缀，命中的 KV cache 直接用于模型 forward 阶段的 attention 计算。")
    else:
        parts.append(
            f"HBM 命中率为 0%：预埋阶段写入的前缀 KV cache 已把 HBM 显存空间占满；正式测试"
            f"阶段新请求的 KV cache 依据 LRU 策略不断写入 HBM，把此前预埋的前缀 KV 覆盖/逐出，"
            f"因此请求虽然带有 {repeat_text} 的前缀，也无法在 HBM 中命中之前预埋的前缀。")

    if external is None:
        parts.append("日志中未解析到外部命中率，外置存储命中过程按 0% 演示。")
    elif external > 0:
        if hbm == 0:
            parts.append(
                f"外部命中率为 {external * 100:.1f}%：请求前缀虽然没有在 HBM 中命中，但在外置"
                "存储中找到了对应的 KV cache，并从外置存储加载回 HBM，用于模型 forward 阶段的"
                "attention 计算。")
        else:
            parts.append(
                f"外部命中率为 {external * 100:.1f}%：HBM 未命中的前缀中有一部分在外置存储中"
                "找到，KV cache 从外置存储加载回 HBM 后参与 attention 计算。")
    else:
        parts.append(
            "外部命中率为 0%：这部分前缀 KV cache 要么没有被写入外置存储，要么超过了外置存储"
            "容量而被驱逐；正式测试阶段既不在 HBM 命中、也不在外置存储命中的前缀，只能由 "
            "prefill 重新计算。")

    if hbm is not None and external is not None:
        miss = max(0.0, 1.0 - hbm - external)
        if miss > 0:
            parts.append(
                f"两部分命中率合计后仍有约 {miss * 100:.1f}% 的前缀 KV 未在缓存中命中，这部分"
                "输入前缀在正式测试阶段由 prefill 重新计算生成。")
    return "".join(parts)


def _animation_case_data(index: int, row: Dict, cache_info: Dict) -> Dict:
    """提取单个用例的动画数据(全部为JSON可序列化类型)。"""
    hbm = _to_float(row.get("hbm_hit_rate"))
    external = _to_float(row.get("external_hit_rate"))
    input_len = _to_int(row.get("input_len"))
    output_len = _to_int(row.get("output_len"))
    total_req = _to_int(row.get("total_req"))
    repeat = _to_float(cache_info.get("repeat_rate"))
    repeat = None if repeat is None else max(0.0, min(1.0, repeat))
    capacity = _to_int(cache_info.get("total_kv_cache"))
    prefix_num = _to_int(row.get("prefix_num")) or total_req
    prefill_tokens = input_len * prefix_num if input_len and prefix_num else None
    demand_ratio = (prefill_tokens / capacity) if prefill_tokens and capacity else None

    label = (f"用例 {index + 1} · "
             f"{_fmt_len(input_len) if input_len else '?'}/"
             f"{_fmt_len(output_len) if output_len else '?'}")
    if total_req:
        label += f" · {total_req}请求"
    return {
        "index": index,
        "label": label,
        "input_len": input_len,
        "output_len": output_len,
        "total_req": total_req,
        "prefix_num": prefix_num,
        "hbm": _cache_frac(hbm),
        "external": _cache_frac(external),
        "repeat_rate": repeat,
        "capacity": capacity or None,
        "prefill_tokens": prefill_tokens,
        "demand_ratio": demand_ratio,
    }


def _animation_case_html(case: Dict) -> str:
    """生成单个用例的动画块(chips + canvas + 控件 + 场景解读)。"""
    esc_label = html.escape(case["label"])
    chips = [
        f"输入 {_fmt_len(case['input_len']) if case['input_len'] else '?'} tokens",
        f"输出 {_fmt_len(case['output_len']) if case['output_len'] else '?'} tokens",
    ]
    if case["total_req"]:
        chips.append(f"请求 {case['total_req']}")
    chips.append(f"HBM 命中率 {_hit_rate_text(case['hbm'])}")
    chips.append(f"外部命中率 {_hit_rate_text(case['external'])}")
    chips.append(f"前缀比例 {_repeat_text(case['repeat_rate'])}")
    if case["capacity"]:
        chips.append(f"总 KV cache {case['capacity']:,} tokens")
    if case["prefill_tokens"]:
        chips.append(f"预埋 KV 需求 ≈ {case['prefill_tokens']:,} tokens（输入长度×前缀数量）")
    if case["demand_ratio"] is not None:
        chips.append(f"预埋需求/容量 ≈ {case['demand_ratio']:.1f}×")
    chip_html = "".join(f'<span class="anim-chip">{html.escape(c)}</span>' for c in chips)

    scenario = _scenario_text(
        None if case["hbm"] is None else case["hbm"] * 100,
        None if case["external"] is None else case["external"] * 100,
        case["repeat_rate"])
    i = case["index"]
    return (
        f'<div class="anim-case" id="animCase{i}"{" hidden" if i else ""}>'
        f'<div class="anim-chips">{chip_html}</div>'
        f'<div class="anim-canvas-wrap"><canvas id="animCanvas{i}" class="anim-canvas" '
        'width="960" height="540">当前浏览器不支持Canvas动画，请使用Chrome/Edge/Firefox等'
        f'现代浏览器查看。</canvas></div>'
        '<div class="anim-controls">'
        f'<button type="button" class="anim-btn" id="animReplay{i}">重新播放</button>'
        f'<button type="button" class="anim-btn" id="animToggle{i}">暂停</button>'
        f'<input type="range" id="animSlider{i}" class="anim-slider" min="0" step="25" value="0" aria-label="动画进度（可拖动）">'
        f'<span class="anim-time" id="animTime{i}">0.0s / 28.0s</span>'
        '</div>'
        '<div class="anim-phase-row">'
        f'<span class="anim-phase" id="animPhase{i}">阶段一：KV Cache 预埋（prefill 数据集写入）</span>'
        '<span class="anim-phase-tip">拖动进度条可回放任意时刻</span></div>'
        '<div class="anim-legend">'
        '<span><span class="dot" style="background:#2563eb"></span>预埋写入/请求查询</span>'
        '<span><span class="dot" style="background:#16a34a"></span>HBM 命中</span>'
        '<span><span class="dot" style="background:#d97706"></span>外置命中并加载回 HBM</span>'
        '<span><span class="dot" style="background:#7c3aed"></span>溢出写入外置存储</span>'
        '<span><span class="dot" style="background:#dc2626"></span>未命中（prefill 重算）</span>'
        '<span><span class="dot" style="background:#94a3b8"></span>被 LRU 逐出/覆盖的旧前缀 KV</span>'
        '</div>'
        f'<p class="anim-scenario"><b>{esc_label} ｜ 命中过程解读：</b>{html.escape(scenario)}</p>'
        '</div>')


# KV Cache命中过程动画模板: __CASES_HTML__/__CASES_JSON__ 为占位符。
# 模板为普通字符串(非f-string), CSS/JS花括号无需转义。
_ANIMATION_TEMPLATE = """<style>
.anim-card{padding:14px 16px;}
.anim-intro{margin:0 0 12px;color:var(--muted);font-size:13.5px;line-height:1.7;}
.anim-tabs{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px;}
.anim-tab{padding:6px 14px;border:1px solid var(--border);border-radius:16px;
 background:#fff;color:var(--text);font-size:13px;cursor:pointer;}
.anim-tab:hover{border-color:var(--primary);color:var(--primary);}
.anim-tab.active{background:var(--primary);border-color:var(--primary);color:#fff;}
.anim-case[hidden]{display:none;}
.anim-chips{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px;}
.anim-chip{display:inline-block;padding:2px 10px;border-radius:10px;
 background:#f1f5f9;border:1px solid var(--border);font-size:12px;color:var(--text);}
.anim-canvas-wrap{background:#fff;border:1px solid var(--border);border-radius:6px;}
.anim-canvas{display:block;width:100%;height:auto;}
.anim-controls{display:flex;align-items:center;gap:10px;margin:10px 0;flex-wrap:wrap;}
.anim-btn{padding:5px 14px;border:1px solid var(--border);border-radius:4px;
 background:#fff;font-size:12.5px;cursor:pointer;}
.anim-btn:hover{border-color:var(--primary);color:var(--primary);}
.anim-slider{flex:1;min-width:240px;accent-color:var(--primary);cursor:pointer;}
.anim-time{font-size:12.5px;color:var(--muted);white-space:nowrap;
 font-variant-numeric:tabular-nums;}
.anim-phase{font-size:13px;font-weight:600;color:var(--primary);}
.anim-phase-row{display:flex;align-items:baseline;gap:10px;margin:0 0 10px;flex-wrap:wrap;}
.anim-phase-tip{font-size:12px;color:var(--muted);}
.anim-legend{display:flex;flex-wrap:wrap;gap:14px;margin:4px 0 10px;
 font-size:12.5px;color:var(--muted);}
.anim-legend .dot{display:inline-block;width:10px;height:10px;border-radius:50%;
 margin-right:5px;vertical-align:middle;}
.anim-scenario{margin:0;padding:10px 12px;background:#f8fafc;
 border:1px solid var(--border);border-radius:4px;font-size:13.5px;
 line-height:1.7;color:var(--text);}
.anim-note{margin:12px 0 0;font-size:12.5px;color:var(--muted);line-height:1.7;}
.anim-empty{color:var(--muted);font-size:13.5px;margin:0;}
</style>
<section id="kvcache-animation">
<h2>KV Cache 命中过程动画</h2>
<div class="card anim-card">
__CASES_HTML__
<script>
(function () {
"use strict";
var CASES = __CASES_JSON__;
var PHASE1 = 14000, PHASE2 = 14000, TOTAL = PHASE1 + PHASE2;
var N1 = 10, N2 = 10;
var state = {active: 0, t: 0, playing: true, last: null, scrubbing: false};

function clamp01(v){return v < 0 ? 0 : v > 1 ? 1 : v;}
function lerp(a, b, u){return a + (b - a) * u;}
function ease(u){u = clamp01(u);return u * u * (3 - 2 * u);}
function polyPoint(pts, u){
  u = clamp01(u);
  var segs = [], total = 0, i;
  for (i = 0; i < pts.length - 1; i++) {
    var d = Math.abs(pts[i+1][0]-pts[i][0]) + Math.abs(pts[i+1][1]-pts[i][1]);
    segs.push(d); total += d;
  }
  if (total === 0) { return [pts[0][0], pts[0][1]]; }
  var target = u * total, acc = 0;
  for (i = 0; i < segs.length; i++) {
    if (target <= acc + segs[i]) {
      var uu = segs[i] === 0 ? 0 : (target - acc) / segs[i];
      return [lerp(pts[i][0], pts[i+1][0], uu), lerp(pts[i][1], pts[i+1][1], uu)];
    }
    acc += segs[i];
  }
  return [pts[pts.length-1][0], pts[pts.length-1][1]];
}

var BOX = {
  src: [20, 110, 180, 190],
  hbm: [350, 90, 330, 140],
  ext: [350, 320, 330, 140],
  att: [760, 130, 180, 140],
  pre: [760, 340, 180, 120]
};
// 层级: 请求源(左) → 存储层HBM(中上)/外置存储(中下) → 计算层(右)
var PATH = {
  writeHbm: [[200, 205], [275, 205], [350, 160]],
  writeExt: [[410, 230], [410, 320]],
  query:    [[200, 205], [275, 205], [350, 160]],
  hbmHit:   [[680, 160], [720, 160], [760, 175]],
  queryExt: [[480, 230], [480, 320]],
  loadBack: [[550, 320], [550, 230]],
  extMiss:  [[515, 460], [620, 480], [760, 415]],
  preAtt:   [[850, 340], [850, 270]]
};
var COLOR = {
  write: "#2563eb", hit: "#16a34a", load: "#d97706", spill: "#7c3aed",
  miss: "#dc2626", evict: "#94a3b8", text: "#1e293b", muted: "#64748b"
};

function frac(v){return v == null ? 0 : clamp01(v);}
function demandRatio(cfg){return cfg.demand_ratio == null ? null : cfg.demand_ratio;}
function externalPresent(cfg){
  var ext = cfg.external == null ? 0 : clamp01(cfg.external);
  return ext > 0;
}
function overflowFrac(cfg){
  if (!externalPresent(cfg)) { return 0; }
  var ext = clamp01(cfg.external), d = demandRatio(cfg);
  return Math.max(ext, 0.3, d == null ? 0 : Math.max(0, d - 1));
}
function hbmFillTarget(cfg){
  var d = demandRatio(cfg);
  if (externalPresent(cfg)) { return 1; }
  if (d != null && d >= 1) { return 1; }
  if (d != null) { return clamp01(Math.max(0.45, d)); }
  return 0.85;
}
function extFillTarget(cfg){
  if (!externalPresent(cfg)) { return 0; }
  return clamp01(Math.max(cfg.external, 0.35));
}

function roundRect(ctx, x, y, w, h, r){
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}
function drawBox(ctx, r, title, sub){
  roundRect(ctx, r[0], r[1], r[2], r[3], 8);
  ctx.fillStyle = "#ffffff"; ctx.fill();
  ctx.strokeStyle = "#cbd5e1"; ctx.lineWidth = 1.5; ctx.stroke();
  ctx.fillStyle = COLOR.text;
  ctx.font = "bold 14px 'Segoe UI','Microsoft YaHei',sans-serif";
  ctx.textAlign = "left"; ctx.textBaseline = "top";
  ctx.fillText(title, r[0] + 12, r[1] + 9);
  if (sub) {
    ctx.fillStyle = COLOR.muted;
    ctx.font = "12px 'Segoe UI','Microsoft YaHei',sans-serif";
    ctx.fillText(sub, r[0] + 12, r[1] + 29);
  }
}
function drawBlocks(ctx, r, fill, evictFrac, hitFrac, baseColor, evictColor){
  // 块区从 r+58 开始, 预留标题/副标题/说明行
  var cols = 15, rows = 5, gx = r[0] + 14, gy = r[1] + 58;
  var cw = (r[2] - 28) / cols, ch = (r[3] - 70) / rows;
  var cells = cols * rows, filled = Math.round(cells * clamp01(fill));
  var evicted = Math.round(cells * clamp01(evictFrac));
  var hitCells = Math.round(cells * clamp01(hitFrac));
  for (var i = 0; i < cells; i++) {
    var col = i % cols, row = Math.floor(i / cols);
    var x = gx + col * cw, y = gy + row * ch;
    if (i >= filled) {
      ctx.strokeStyle = "#e2e8f0"; ctx.lineWidth = 1;
      ctx.strokeRect(x + 1, y + 1, cw - 3, ch - 3);
    } else if (i < evicted) {
      ctx.fillStyle = evictColor;
      ctx.fillRect(x + 1, y + 1, cw - 3, ch - 3);
    } else if (i < hitCells) {
      ctx.fillStyle = "#bbf7d0";
      ctx.fillRect(x + 1, y + 1, cw - 3, ch - 3);
    } else {
      ctx.fillStyle = baseColor;
      ctx.fillRect(x + 1, y + 1, cw - 3, ch - 3);
    }
  }
}
function drawPath(ctx, pts, label, labelAt, showLabel){
  ctx.strokeStyle = "#cbd5e1"; ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(pts[0][0], pts[0][1]);
  for (var i = 1; i < pts.length; i++) { ctx.lineTo(pts[i][0], pts[i][1]); }
  ctx.stroke();
  // 末端箭头, 标明数据流向
  var n = pts.length;
  var dx = pts[n-1][0] - pts[n-2][0], dy = pts[n-1][1] - pts[n-2][1];
  var len = Math.sqrt(dx * dx + dy * dy) || 1;
  var ux = dx / len, uy = dy / len;
  var tipX = pts[n-1][0], tipY = pts[n-1][1];
  ctx.beginPath();
  ctx.moveTo(tipX, tipY);
  ctx.lineTo(tipX - 10 * ux + 5 * uy, tipY - 10 * uy - 5 * ux);
  ctx.lineTo(tipX - 10 * ux - 5 * uy, tipY - 10 * uy + 5 * ux);
  ctx.closePath();
  ctx.fillStyle = "#94a3b8"; ctx.fill();
  if (showLabel && label) {
    ctx.fillStyle = COLOR.muted;
    ctx.font = "11.5px 'Segoe UI','Microsoft YaHei',sans-serif";
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(label, labelAt[0], labelAt[1]);
  }
}
function drawParticle(ctx, p, color, text){
  ctx.beginPath();
  ctx.arc(p[0], p[1], 9, 0, Math.PI * 2);
  ctx.fillStyle = color; ctx.fill();
  ctx.strokeStyle = "#ffffff"; ctx.lineWidth = 2; ctx.stroke();
  if (text) {
    ctx.fillStyle = COLOR.text;
    ctx.font = "bold 11px 'Segoe UI','Microsoft YaHei',sans-serif";
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(text, p[0], p[1] - 15);
  }
}
function drawFlash(ctx, at, t0, t, color){
  var u = (t - t0) / 900;
  if (u < 0 || u > 1) { return; }
  ctx.beginPath();
  ctx.arc(at[0], at[1], 12 + 26 * u, 0, Math.PI * 2);
  ctx.strokeStyle = color; ctx.globalAlpha = 1 - u; ctx.lineWidth = 3;
  ctx.stroke(); ctx.globalAlpha = 1;
}

function phase1Routes(cfg){
  var routes = [], extCount = Math.round(N1 * overflowFrac(cfg));
  var span = PHASE1 * 0.6 / N1;
  for (var i = 0; i < N1; i++) {
    var toExt = i >= N1 - extCount;
    routes.push({
      start: 300 + i * span, dur: 1500,
      pts: toExt ? PATH.writeExt : PATH.writeHbm,
      color: toExt ? COLOR.spill : COLOR.write,
      text: "预填" + (i + 1)
    });
  }
  return routes;
}
function phase2Routes(cfg){
  var routes = [], hit = Math.round(N2 * frac(cfg.hbm));
  var ext = Math.round(N2 * frac(cfg.external));
  var span = PHASE2 * 0.45 / N2;
  for (var j = 0; j < N2; j++) {
    var kind = j < hit ? "hbm" : (j < hit + ext ? "ext" : "miss");
    var segs = [
      {pts: PATH.query, dur: 1400, color: COLOR.write, text: "请求" + (j + 1)}
    ];
    if (kind === "hbm") {
      segs.push({pts: PATH.hbmHit, dur: 1500, color: COLOR.hit, text: "HBM命中"});
    } else if (kind === "ext") {
      segs.push({pts: PATH.queryExt, dur: 1100, color: COLOR.miss, text: "HBM未命中"});
      segs.push({pts: PATH.loadBack, dur: 1100, color: COLOR.load, text: "外置命中加载"});
      segs.push({pts: PATH.hbmHit, dur: 1500, color: COLOR.hit, text: "参与attention"});
    } else {
      segs.push({pts: PATH.queryExt, dur: 1100, color: COLOR.miss, text: "HBM未命中"});
      segs.push({pts: PATH.extMiss, dur: 1100, color: COLOR.miss, text: "外置未命中"});
      segs.push({pts: PATH.preAtt, dur: 1100, color: COLOR.write, text: "prefill重算"});
    }
    var start = PHASE1 + 300 + j * span, cursor = start;
    segs.forEach(function (s) { s.start = cursor; cursor += s.dur; });
    routes.push({kind: kind, dispatch: start, segs: segs});
  }
  return routes;
}

function drawCase(ctx, cfg, t){
  var W = 960, H = 540;
  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = "#f8fafc"; ctx.fillRect(0, 0, W, H);
  var inPhase1 = t < PHASE1;
  var p1 = ease((t - 300) / (PHASE1 - 1600));
  var p2 = ease((t - PHASE1 - 300) / (PHASE2 - 2400));
  var FONT = "'Segoe UI','Microsoft YaHei',sans-serif";

  ctx.fillStyle = inPhase1 ? "#dbeafe" : "#dcfce7";
  roundRect(ctx, 12, 10, 936, 44, 8); ctx.fill();
  ctx.fillStyle = COLOR.text;
  ctx.font = "bold 15px " + FONT;
  ctx.textAlign = "left"; ctx.textBaseline = "middle";
  ctx.fillText(inPhase1 ? "阶段一：KV Cache 预埋（prefill 数据集写入）"
                        : "阶段二：正式测试（带前缀请求查询命中）", 26, 25);
  ctx.fillStyle = COLOR.muted;
  ctx.font = "12px " + FONT;
  ctx.fillText(inPhase1
    ? "预埋请求把可复用前缀的 KV cache 写入 HBM 显存；HBM 占满后溢出写入外置存储"
    : "请求先查询 HBM；未命中转查外置存储并加载回 HBM；仍未命中由 prefill 重新计算",
    26, 43);
  ctx.fillStyle = "#e2e8f0"; ctx.fillRect(12, 60, 936, 6);
  ctx.fillStyle = "#2563eb"; ctx.fillRect(12, 60, 936 * (t / TOTAL), 6);
  // 阶段分界刻度: 前半预埋 / 后半正式测试
  ctx.fillStyle = "#94a3b8"; ctx.fillRect(12 + 936 * 0.5, 56, 2, 14);
  ctx.fillStyle = COLOR.muted;
  ctx.font = "10.5px " + FONT;
  ctx.textAlign = "center"; ctx.textBaseline = "top";
  ctx.fillText("预埋阶段", 12 + 936 * 0.25, 70);
  ctx.fillText("正式测试", 12 + 936 * 0.75, 70);

  // 连线按层级: 请求→HBM, HBM→attention, HBM↕外置, 外置→prefill, prefill→attention
  drawPath(ctx, PATH.writeHbm, "查询 / 预填写入", [275, 182], true);
  drawPath(ctx, PATH.hbmHit, "HBM 命中", [720, 140], !inPhase1);
  drawPath(ctx, PATH.queryExt, "未命中转查", [480, 252], !inPhase1);
  drawPath(ctx, PATH.loadBack, "加载回 HBM", [550, 288],
           !inPhase1 && frac(cfg.external) > 0);
  drawPath(ctx, PATH.extMiss, "外置未命中 → prefill 重算", [630, 502], !inPhase1);
  drawPath(ctx, PATH.preAtt, "重算 KV → attention", [850, 303], !inPhase1);
  if (inPhase1 && externalPresent(cfg)) {
    drawPath(ctx, PATH.writeExt, "溢出写入", [410, 272], true);
  }

  drawBox(ctx, BOX.hbm, "HBM 显存 KV Cache", "LRU 淘汰策略");
  var hbmFill = hbmFillTarget(cfg) * p1;
  var evictFrac = inPhase1 ? 0 : p2 * (1 - frac(cfg.hbm));
  drawBlocks(ctx, BOX.hbm, hbmFill, evictFrac, inPhase1 ? 0 : frac(cfg.hbm) * p2,
             "#93c5fd", COLOR.evict);
  ctx.fillStyle = COLOR.muted;
  ctx.font = "12px " + FONT;
  ctx.textAlign = "right"; ctx.textBaseline = "top";
  ctx.fillText("已用 " + Math.round(hbmFill * 100) + "%",
               BOX.hbm[0] + BOX.hbm[2] - 12, BOX.hbm[1] + 29);
  if (!inPhase1 && frac(cfg.hbm) === 0) {
    ctx.fillStyle = COLOR.miss;
    ctx.font = "11.5px " + FONT;
    ctx.fillText("LRU：新请求覆盖旧前缀",
                 BOX.hbm[0] + BOX.hbm[2] - 12, BOX.hbm[1] + 44);
  }

  drawBox(ctx, BOX.ext, "外置存储（DRAM 分级缓存）",
          externalPresent(cfg) ? "承接 HBM 溢出的 KV cache"
                               : "未写入或已被容量上限驱逐");
  drawBlocks(ctx, BOX.ext, extFillTarget(cfg) * (inPhase1 ? p1 : 1), 0, 0,
             "#c4b5fd", COLOR.evict);
  ctx.fillStyle = COLOR.muted;
  ctx.font = "12px " + FONT;
  ctx.textAlign = "right";
  ctx.fillText("已用 " + Math.round(extFillTarget(cfg) * (inPhase1 ? p1 : 1) * 100) + "%",
               BOX.ext[0] + BOX.ext[2] - 12, BOX.ext[1] + 29);

  drawBox(ctx, BOX.src, inPhase1 ? "预埋请求（prefill）" : "正式请求（带前缀）",
          inPhase1 ? "request rate = 0" : "前缀比例 repeat_rate");
  drawBox(ctx, BOX.pre, "Prefill 重算", "未命中的前缀重新计算");
  drawBox(ctx, BOX.att, "Forward / Attention", "使用命中或重算的 KV");

  if (inPhase1) {
    phase1Routes(cfg).forEach(function (r) {
      var u = (t - r.start) / r.dur;
      if (u >= 0 && u <= 1) {
        drawParticle(ctx, polyPoint(r.pts, ease(u)), r.color, r.text);
      } else if (u > 1 && u < 1.6) {
        drawFlash(ctx, r.pts[r.pts.length - 1], r.start + r.dur, t, r.color);
      }
    });
    ctx.fillStyle = COLOR.muted;
    ctx.font = "12px " + FONT;
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    var sent = Math.min(N1, Math.max(0, Math.floor((t - 300) / (PHASE1 * 0.6 / N1)) + 1));
    ctx.fillText("已发送 " + sent + "/" + N1, BOX.src[0] + 90, BOX.src[1] + 120);
  } else {
    var done = 0;
    phase2Routes(cfg).forEach(function (route) {
      route.segs.forEach(function (s) {
        var u = (t - s.start) / s.dur;
        if (u >= 0 && u <= 1) {
          drawParticle(ctx, polyPoint(s.pts, ease(u)), s.color, s.text);
        }
      });
      if (route.kind === "hbm") {
        drawFlash(ctx, PATH.query[PATH.query.length - 1],
                  route.segs[0].start + 1400, t, COLOR.hit);
      } else if (route.kind === "ext") {
        drawFlash(ctx, PATH.queryExt[PATH.queryExt.length - 1],
                  route.segs[1].start + 1100, t, COLOR.load);
      } else {
        drawFlash(ctx, PATH.extMiss[PATH.extMiss.length - 1],
                  route.segs[2].start + 1100, t, COLOR.miss);
      }
      var last = route.segs[route.segs.length - 1];
      if (t > last.start + last.dur) { done += 1; }
    });
    ctx.fillStyle = COLOR.muted;
    ctx.font = "12px " + FONT;
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText("已完成请求 " + done + "/" + N2, BOX.src[0] + 90, BOX.src[1] + 120);
  }

  ctx.fillStyle = COLOR.muted;
  ctx.font = "12px " + FONT;
  ctx.textAlign = "left"; ctx.textBaseline = "bottom";
  ctx.fillText("HBM 命中率 " + (cfg.hbm == null ? "未知" : (cfg.hbm * 100).toFixed(1) + "%") +
               " ｜ 外部命中率 " + (cfg.external == null ? "未知" : (cfg.external * 100).toFixed(1) + "%") +
               " ｜ 前缀比例 " + (cfg.repeat_rate == null ? "未知" : Math.round(cfg.repeat_rate * 100) + "%"),
               16, 534);
}

var tabsEl = document.getElementById("animTabs");
var tabBtns = [];
CASES.forEach(function (cfg, i) {
  var btn = document.createElement("button");
  btn.type = "button";
  btn.className = "anim-tab" + (i === 0 ? " active" : "");
  btn.textContent = cfg.label;
  btn.addEventListener("click", function () { activate(i); });
  tabsEl.appendChild(btn);
  tabBtns.push(btn);

  var replay = document.getElementById("animReplay" + i);
  var toggle = document.getElementById("animToggle" + i);
  if (replay) {
    replay.addEventListener("click", function () {
      state.t = 0; state.playing = true; syncToggle();
    });
  }
  if (toggle) {
    toggle.addEventListener("click", function () {
      state.playing = !state.playing; syncToggle();
    });
  }
  var slider = document.getElementById("animSlider" + i);
  if (slider) {
    slider.max = String(TOTAL);
    // 拖动时暂停播放, 松开后恢复拖动前的播放状态
    slider.addEventListener("pointerdown", function () {
      state.scrubbing = true;
      state.resumeAfterScrub = state.playing;
      state.playing = false;
      syncToggle();
    });
    slider.addEventListener("pointerup", function () {
      state.scrubbing = false;
      state.playing = !!state.resumeAfterScrub;
      syncToggle();
    });
    slider.addEventListener("input", function () {
      var v = parseInt(slider.value, 10);
      if (!isNaN(v)) {
        state.t = Math.max(0, Math.min(TOTAL - 1, v));
        state.playing = false;
        syncToggle();
      }
    });
  }
});

function syncToggle(){
  var btn = document.getElementById("animToggle" + state.active);
  if (btn) { btn.textContent = state.playing ? "暂停" : "继续"; }
}
function activate(i){
  if (i < 0 || i >= CASES.length) { return; }
  state.active = i; state.t = 0; state.playing = true;
  CASES.forEach(function (_c, j) {
    var el = document.getElementById("animCase" + j);
    if (el) { el.hidden = (j !== i); }
  });
  tabBtns.forEach(function (b, j) { b.classList.toggle("active", j === i); });
  syncProgress(true);
  syncToggle();
}
activate(0);

Array.prototype.forEach.call(
  document.querySelectorAll("tr.case-row"), function (row) {
    row.addEventListener("click", function () {
      var i = parseInt(row.getAttribute("data-case"), 10);
      if (!isNaN(i)) {
        activate(i);
        var sec = document.getElementById("kvcache-animation");
        if (sec && sec.scrollIntoView) { sec.scrollIntoView({behavior: "smooth"}); }
      }
    });
  });

function phaseLabel(t){
  var el = document.getElementById("animPhase" + state.active);
  if (!el) { return; }
  el.textContent = t < PHASE1
    ? "阶段一：KV Cache 预埋（prefill 数据集写入）"
    : "阶段二：正式测试（带前缀请求查询命中）";
}

function syncProgress(force){
  var slider = document.getElementById("animSlider" + state.active);
  var timeEl = document.getElementById("animTime" + state.active);
  if (slider && (force || !state.scrubbing)) {
    slider.value = String(Math.round(state.t));
  }
  if (timeEl) {
    timeEl.textContent = (state.t / 1000).toFixed(1) + "s / " +
                         (TOTAL / 1000).toFixed(1) + "s";
  }
}

function frame(now){
  if (state.last == null) { state.last = now; }
  var dt = now - state.last;
  state.last = now;
  if (dt > 0 && dt < 500 && state.playing) {
    state.t = (state.t + dt) % TOTAL;
  }
  var cfg = CASES[state.active];
  var canvas = document.getElementById("animCanvas" + state.active);
  if (canvas && canvas.getContext) {
    drawCase(canvas.getContext("2d"), cfg, state.t);
  }
  phaseLabel(state.t);
  syncProgress(false);
  requestAnimationFrame(frame);
}
if (CASES.length > 0) { requestAnimationFrame(frame); }
})();
</script>
</div>
</section>
"""


def render_kvcache_animation_html(results: List[Dict],
                                   cache_info: Optional[Dict] = None) -> str:
    """渲染KV Cache命中过程动画章节(自包含, 内联JS/Canvas, 无外部依赖)。"""
    cache_info = cache_info or {}
    if not results:
        return ('<section id="kvcache-animation"><h2>KV Cache 命中过程动画</h2>'
                '<div class="card anim-card">'
                '<p class="anim-empty">未提取到有效结果，无法生成命中过程动画。</p>'
                '</div></section>')
    cases = [_animation_case_data(i, row, cache_info)
             for i, row in enumerate(results)]
    intro = ('<p class="anim-intro">AISBench prefix 测试分两个阶段：先用 prefill 数据集'
             '（request rate = 0）把可复用前缀的 KV cache 预埋进推理系统缓存（先填 HBM 显存，'
             'HBM 占满后溢出写入外置存储）；正式测试阶段发送带前缀比例（repeat_rate）的请求，'
             '先查询 HBM，未命中转查外置存储并把命中的 KV cache 加载回 HBM，仍未命中由 '
             'prefill 重新计算。点击上方用例标签或“测试结果”表格中的用例行，切换查看对应用例'
             '的动画。动画支持暂停/继续与重新播放，拖动进度条可回放任意时刻（前半段为预埋'
             '阶段，后半段为正式测试阶段）。</p>')
    cases_html = (intro + '<div class="anim-tabs" id="animTabs"></div>'
                  + "".join(_animation_case_html(c) for c in cases)
                  + '<p class="anim-note">动画为示意性演示：色块数量表示 KV cache 空间的相对'
                    '占用，不代表精确容量；命中率、前缀比例与请求参数均取自本用例的实际数据。'
                    'HBM 命中率为 0 时展示预埋撑爆 HBM、正式测试阶段新请求 KV 依据 LRU 覆盖'
                    '旧前缀的过程；外部命中率为 0 时外置存储不展示已写入内容（未写入或已被'
                    '驱逐）。</p>'
                  + '<noscript><p class="anim-empty">浏览器需启用 JavaScript 才能播放动画。</p>'
                    '</noscript>')
    return (_ANIMATION_TEMPLATE
            .replace("__CASES_HTML__", cases_html)
            .replace("__CASES_JSON__", json.dumps(cases, ensure_ascii=False)))
