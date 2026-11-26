#!/usr/bin/env python3
"""
单次测试执行报告生成器:
在测试执行流水线完成后, 把模型信息、测试配置、执行命令、
测试结果和结果解读汇总为一个自包含HTML报告(无需外部依赖)。
"""

import html
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from kvcache_animation import render_kvcache_animation_html


# 报告中展示的核心结果列 (字段, 表头, 单位)
RESULT_COLUMNS = [
    ("input_len", "输入长度", "tokens"),
    ("output_len", "输出长度", "tokens"),
    ("total_req", "请求数", "req"),
    ("max_cc", "最大并发", ""),
    ("cc", "实际并发", ""),
    ("TTFT_avg", "TTFT平均", "ms"),
    ("TPOT_avg", "TPOT平均", "ms"),
    ("output_throughput", "输出吞吐", "tok/s"),
    ("input_token_throughput", "输入吞吐", "tok/s"),
    ("qps", "QPS", "req/s"),
    ("hbm_hit_rate", "HBM命中率", "%"),
    ("external_hit_rate", "外部命中率", "%"),
    ("E2E_time", "E2E时间", "s"),
]


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


def _fmt_value(value, field: str = "") -> str:
    if field in ("input_len", "output_len"):
        return _fmt_len(value)
    if value is None or value == "":
        return "-"
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    return str(value)


def _to_float(value) -> Optional[float]:
    """宽容地把日志/CSV中的数值字段转为float(支持带千分位逗号)。"""
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
    """把百分数命中率转为0~1的小数并限幅。"""
    if value is None:
        return None
    return max(0.0, min(100.0, value)) / 100.0


def _hit_rate_text(frac: Optional[float]) -> str:
    if frac is None:
        return "未解析到"
    return f"{frac * 100:.1f}%"


def _repeat_text(repeat: Optional[float]) -> str:
    if repeat is None:
        return "未提供"
    return f"{repeat * 100:.0f}%"


def _scenario_text(hbm: Optional[float], external: Optional[float],
                   repeat: Optional[float]) -> str:
    """按AISBench prefix测试两阶段原理, 描述该用例的KV cache命中过程。"""
    hbm = _cache_frac(hbm)
    external = _cache_frac(external)
    repeat_text = _repeat_text(repeat)
    parts: List[str] = []

    if hbm is None:
        parts.append("本用例日志中未解析到 HBM 命中率，动画按 0% 演示。")
    elif hbm > 0:
        parts.append(
            f"HBM 命中率为 {hbm * 100:.1f}%：预埋阶段写入 HBM 的前缀 KV cache "
            f"在正式测试阶段仍有一部分留在 HBM 中，带前缀（repeat_rate = {repeat_text}）的请求"
            "直接在 HBM 中命中这部分前缀，命中的 KV cache 直接用于模型 forward 阶段的 attention 计算。")
    else:
        parts.append(
            f"HBM 命中率为 0%：预埋阶段写入的前缀 KV cache 已把 HBM 显存空间占满；"
            f"正式测试阶段新请求的 KV cache 依据 LRU 策略不断写入 HBM，"
            f"把此前预埋的前缀 KV 覆盖/逐出，因此请求虽然带有 {repeat_text} 的前缀，"
            "也无法在 HBM 中命中之前预埋的前缀。")

    if external is None:
        parts.append("日志中未解析到外部命中率，外置存储命中过程按 0% 演示。")
    elif external > 0:
        if hbm == 0:
            parts.append(
                f"外部命中率为 {external * 100:.1f}%：请求前缀虽然没有在 HBM 中命中，"
                "但在外置存储中找到了对应的 KV cache，并从外置存储加载回 HBM，"
                "用于模型 forward 阶段的 attention 计算。")
        else:
            parts.append(
                f"外部命中率为 {external * 100:.1f}%：HBM 未命中的前缀中有一部分在外置存储中找到，"
                "KV cache 从外置存储加载回 HBM 后参与 attention 计算。")
    else:
        parts.append(
            "外部命中率为 0%：这部分前缀 KV cache 要么没有被写入外置存储，"
            "要么超过了外置存储容量而被驱逐；正式测试阶段既不在 HBM 命中、"
            "也不在外置存储命中的前缀，只能由 prefill 重新计算。")

    if hbm is not None and external is not None:
        miss = max(0.0, 1.0 - hbm - external)
        if miss > 0:
            parts.append(
                f"两部分命中率合计后仍有约 {miss * 100:.1f}% 的前缀 KV 未在缓存中命中，"
                "这部分输入前缀在正式测试阶段由 prefill 重新计算生成。")
    return "".join(parts)


def _interpret_results(results: List[Dict]) -> List[Tuple[str, str]]:
    """根据解析出的结果生成指标含义与具体数值的解读要点(不做正常/异常判断)。"""
    notes: List[Tuple[str, str]] = []
    if not results:
        notes.append(("warning", "本次执行未从日志中提取到有效结果。请查看结果目录中的执行日志与 preflight.log，确认容器内服务状态与脚本错误信息。"))
        return notes

    def to_float(row: Dict, key: str) -> Optional[float]:
        try:
            if row.get(key) in (None, ""):
                return None
            return float(row[key])
        except (TypeError, ValueError):
            return None

    hbm = [to_float(row, "hbm_hit_rate") for row in results]
    hbm = [v for v in hbm if v is not None]
    if hbm:
        notes.append(("info", f"HBM 命中率：各用例分别为 {', '.join(f'{v:.1f}%' for v in hbm)}，平均 {sum(hbm) / len(hbm):.1f}%，范围 {min(hbm):.1f}% ~ {max(hbm):.1f}%。该指标表示 KV cache 前缀命中 HBM 显存缓存的比例。"))

    external = [to_float(row, "external_hit_rate") for row in results]
    external = [v for v in external if v is not None]
    if external:
        notes.append(("info", f"外部命中率：各用例分别为 {', '.join(f'{v:.1f}%' for v in external)}，平均 {sum(external) / len(external):.1f}%。该指标表示超出 HBM 容量、由外部缓存介质（如主机内存）服务的 KV 访问比例。"))

    ttft = [to_float(row, "TTFT_avg") for row in results]
    ttft = [v for v in ttft if v is not None]
    if ttft:
        notes.append(("info", f"TTFT 平均值：各用例分别为 {', '.join(f'{v:.2f}' for v in ttft)} ms，范围 {min(ttft):.2f} ~ {max(ttft):.2f} ms。TTFT（Time To First Token）指从请求发出到收到第一个输出 token 的延迟。"))

    tpot = [to_float(row, "TPOT_avg") for row in results]
    tpot = [v for v in tpot if v is not None]
    if tpot:
        notes.append(("info", f"TPOT 平均值：各用例分别为 {', '.join(f'{v:.2f}' for v in tpot)} ms，范围 {min(tpot):.2f} ~ {max(tpot):.2f} ms。TPOT（Time Per Output Token）指生成每个输出 token 的平均时间。"))

    output_tp = [to_float(row, "output_throughput") for row in results]
    output_tp = [v for v in output_tp if v is not None]
    if output_tp:
        notes.append(("info", f"输出吞吐：各用例分别为 {', '.join(f'{v:.2f}' for v in output_tp)} tok/s，合计 {sum(output_tp):.2f} tok/s，最高 {max(output_tp):.2f} tok/s。该指标指每秒生成的输出 token 数量。"))

    qps = [to_float(row, "qps") for row in results]
    qps = [v for v in qps if v is not None]
    if qps:
        notes.append(("info", f"QPS：各用例分别为 {', '.join(f'{v:.2f}' for v in qps)} req/s。该指标指每秒完成的请求数量。"))

    e2e = [to_float(row, "E2E_time") for row in results]
    e2e = [v for v in e2e if v is not None]
    if e2e:
        notes.append(("info", f"E2E 时间：各用例分别为 {', '.join(f'{v:.2f}' for v in e2e)} s。该指标指单个用例从开始执行到全部请求完成的总耗时。"))

    return notes


def render_test_report(path: str, task_name: str, model_info: Dict[str, str],
                       test_config: Dict[str, str], commands: List[str],
                       results: List[Dict], environment: Dict[str, str],
                       status: str = "completed",
                       cache_info: Optional[Dict] = None) -> str:
    """生成单次测试执行的自包含HTML报告, 返回报告文件路径。

    model_info: MODEL_NAME/MODEL_PATH/HOST_IP/HOST_PORT 等
    test_config: KV cache、DP、前缀命中率、请求发送速率、用例数等
    commands: 每个测试用例的执行命令
    results: parse_log_directory 返回的结果行
    environment: 容器/镜像/结果目录等环境信息
    """

    def esc(value) -> str:
        return html.escape(str(value if value is not None else ""))

    def table(pairs: List[Tuple[str, str]]) -> str:
        return "".join(f"<tr><th>{esc(k)}</th><td>{esc(v)}</td></tr>"
                       for k, v in pairs if str(v or "").strip() != "")

    model_rows = table([(k, v) for k, v in model_info.items()])
    config_rows = table([(k, v) for k, v in test_config.items()])
    env_rows = table([(k, v) for k, v in environment.items()])
    command_html = "".join(
        f'<div class="cmd"><span class="idx">#{i}</span><code>{esc(cmd)}</code></div>'
        for i, cmd in enumerate(commands, 1))

    columns = [(field, name, unit) for field, name, unit in RESULT_COLUMNS]
    head_html = "".join(
        f"<th>{esc(name)}{esc(f' ({unit})' if unit else '')}</th>"
        for _f, name, unit in columns)
    body_html = ""
    if results:
        body_html = "".join(
            f'<tr class="case-row" data-case="{i}" title="点击查看该用例的 KV Cache 命中过程动画">'
            + "".join(f"<td>{esc(_fmt_value(row.get(field), field))}</td>"
                      for field, _n, _u in columns) + "</tr>"
            for i, row in enumerate(results))
    else:
        span = len(columns)
        body_html = (f'<tr><td class="empty" colspan="{span}">'
                     '未提取到有效结果（请查看执行日志）</td></tr>')

    notes = _interpret_results(results)
    note_html = "".join(
        f'<li class="{level}">{esc(text)}</li>' for level, text in notes)

    status_text = {
        "completed": "已完成", "abnormal": "异常终止",
        "no_results": "无有效结果", "running": "运行中",
    }.get(status, status)
    status_class = "ok" if status == "completed" else "warn"
    animation_html = render_kvcache_animation_html(results, cache_info)
    result_hint = ('<span class="hint">（点击用例行可在下方动画中查看该用例的 '
                   'KV Cache 命中过程）</span>' if results else "")

    document = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AISBench 测试报告 - {esc(task_name)}</title>
<style>
:root {{ --bg:#f8fafc; --card:#ffffff; --border:#e2e8f0; --text:#1e293b;
         --muted:#64748b; --primary:#2563eb; --ok:#16a34a; --warn:#d97706; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; padding:24px; background:var(--bg); color:var(--text);
       font-family:"Segoe UI","Microsoft YaHei",Arial,sans-serif; }}
.container {{ max-width: 1280px; margin: 0 auto; }}
h1 {{ margin:0 0 6px; font-size:24px; color:var(--primary); }}
.meta {{ color:var(--muted); font-size:13px; margin-bottom:18px; }}
.status {{ display:inline-block; padding:2px 10px; border-radius:10px;
          font-size:12px; color:#fff; margin-left:10px; }}
.status.ok {{ background:var(--ok); }} .status.warn {{ background:var(--warn); }}
h2 {{ margin:28px 0 10px; font-size:18px; border-bottom:1px solid var(--border);
     padding-bottom:6px; }}
.hint {{ font-size:12px; color:var(--muted); font-weight:normal; margin-left:8px; }}
.card {{ background:var(--card); border:1px solid var(--border);
        border-radius:6px; padding:14px 16px; }}
.kv table {{ border-collapse:collapse; width:100%; }}
.kv th {{ text-align:left; color:var(--muted); font-weight:600; width:230px;
         padding:4px 14px 4px 0; white-space:nowrap; vertical-align:top; }}
.kv td {{ padding:4px 0; word-break:break-all; }}
.cmd {{ display:flex; gap:10px; margin:8px 0; align-items:flex-start; }}
.cmd .idx {{ color:var(--muted); font-size:12px; min-width:36px; padding-top:3px; }}
.cmd code {{ display:block; flex:1; background:#f1f5f9; border:1px solid var(--border);
            border-radius:4px; padding:8px 10px; font-size:12.5px;
            font-family:Consolas,"Courier New",monospace; white-space:pre-wrap;
            word-break:break-all; }}
.data {{ overflow-x:auto; }}
.data table {{ border-collapse:collapse; width:100%; font-size:13px; }}
.data th,.data td {{ border:1px solid var(--border); padding:6px 10px;
                    text-align:center; white-space:nowrap; }}
.data th {{ background:#f1f5f9; }}
.data td.empty {{ color:var(--muted); padding:18px; }}
tr.case-row {{ cursor:pointer; }}
tr.case-row:hover {{ background:#eff6ff; }}
ul.notes {{ list-style:none; padding:0; margin:0; }}
ul.notes li {{ padding:8px 12px 8px 30px; margin:6px 0; border-radius:4px;
              position:relative; background:var(--card);
              border:1px solid var(--border); font-size:13.5px; line-height:1.6; }}
ul.notes li.info::before {{ content:"i"; background:var(--primary); }}
ul.notes li.good::before {{ content:"✓"; background:var(--ok); }}
ul.notes li.warning::before {{ content:"!"; background:var(--warn); }}
ul.notes li::before {{ position:absolute; left:8px; top:9px; width:16px; height:16px;
                      border-radius:50%; color:#fff; font-size:11px; font-weight:bold;
                      display:flex; align-items:center; justify-content:center; }}
footer {{ margin-top:24px; color:var(--muted); font-size:12px; }}
</style>
</head>
<body><div class="container">
<h1>AISBench 测试报告<span class="status {status_class}">{esc(status_text)}</span></h1>
<div class="meta">任务：{esc(task_name)} ｜ 生成时间：{esc(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}</div>

<h2>模型与服务</h2>
<div class="card kv"><table>{model_rows or '<tr><td class="empty">无模型信息</td></tr>'}</table></div>

<h2>测试配置</h2>
<div class="card kv"><table>{config_rows or '<tr><td class="empty">无配置信息</td></tr>'}</table></div>

<h2>执行环境</h2>
<div class="card kv"><table>{env_rows}</table></div>

<h2>执行命令（{len(commands)} 个测试用例）</h2>
<div class="card">{command_html or '<span class="empty">无执行命令</span>'}</div>

<h2>测试结果{result_hint}</h2>
<div class="card data"><table><thead><tr>{head_html}</tr></thead>
<tbody>{body_html}</tbody></table></div>

{animation_html}

<h2>结果解读</h2>
<ul class="notes">{note_html}</ul>

<footer>AISBench-Prefix-Tools</footer>
</div></body>
</html>
"""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(document)
    return path
