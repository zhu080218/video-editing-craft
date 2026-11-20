#!/usr/bin/env python3
"""EDL 与字幕校验器（纯 Python，不依赖 FFmpeg）。

在渲染前检查剪辑决策单：片段是否逆序/重叠/过短、是否落在帧边界、
字幕是否重叠或超出片长、CPS 是否超限、单行是否过长。

用法：
  python edl_check.py --edl edl.json
  python edl_check.py --edl edl.json --fps 30 --min-seg 0.3 --padding 0.05 --cps-max 9
  python edl_check.py --edl edl.json --json

退出码：0 通过（可有告警）；1 有阻塞级问题；2 文件或格式错误。
"""
import argparse
import json
import sys

ERROR = "ERROR"
WARN = "WARN"


def read_edl(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"错误：找不到 {path}", file=sys.stderr)
        raise SystemExit(2)
    except json.JSONDecodeError as e:
        print(f"错误：{path} 不是合法 JSON（{e}）", file=sys.stderr)
        raise SystemExit(2)
    if not isinstance(data, dict):
        print("错误：EDL 顶层必须是对象", file=sys.stderr)
        raise SystemExit(2)
    return data


def near_frame_boundary(t: float, fps: float, tol_ratio: float = 0.25) -> bool:
    if fps <= 0:
        return True
    frame = t * fps
    return abs(frame - round(frame)) <= tol_ratio


def char_count(text: str) -> int:
    return len("".join(text.split()))


def main() -> int:
    ap = argparse.ArgumentParser(description="EDL / 字幕校验器")
    ap.add_argument("--edl", required=True, help="EDL JSON 路径")
    ap.add_argument("--fps", type=float, default=None, help="时间线帧率（不填取 EDL 里的 fps，默认 30）")
    ap.add_argument("--min-seg", type=float, default=0.3, help="单段最短时长（秒），默认 0.3")
    ap.add_argument("--padding", type=float, default=0.05, help="切点安全余量（秒），默认 0.05")
    ap.add_argument("--cps-max", type=float, default=9.0, help="字幕每秒最大字数，默认 9")
    ap.add_argument("--max-line-chars", type=int, default=14, help="字幕单行最大字数，默认 14")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    args = ap.parse_args()

    edl = read_edl(args.edl)
    fps = args.fps or float(edl.get("fps") or 30.0)

    issues = []
    rows = []

    def add(level: str, code: str, msg: str) -> None:
        issues.append({"level": level, "code": code, "message": msg})

    segments = edl.get("segments")
    if not isinstance(segments, list) or not segments:
        add(ERROR, "E1", "segments 缺失或为空")
        segments = []

    total_out = 0.0
    prev_out = None
    for i, seg in enumerate(segments, start=1):
        if not isinstance(seg, dict):
            add(ERROR, "E2", f"第 {i} 段不是对象")
            continue
        try:
            tin = float(seg["in"])
            tout = float(seg["out"])
        except (KeyError, TypeError, ValueError):
            add(ERROR, "E2", f"第 {i} 段缺少合法的 in / out")
            continue
        speed = float(seg.get("speed") or 1.0)
        if speed <= 0:
            add(ERROR, "E3", f"第 {i} 段 speed 必须为正数")
            speed = 1.0
        if tin < 0:
            add(ERROR, "E4", f"第 {i} 段 in 为负值")
        if tout <= tin:
            add(ERROR, "E4", f"第 {i} 段 out({tout}) 不大于 in({tin})")
            continue

        src_dur = tout - tin
        out_dur = src_dur / speed
        total_out += out_dur

        if out_dur < args.min_seg:
            add(ERROR, "E5", f"第 {i} 段输出时长 {out_dur:.2f}s 低于最短 {args.min_seg}s（观众看不见就闪过去了）")
        if out_dur < args.padding * 2:
            add(WARN, "W1", f"第 {i} 段时长 {out_dur:.2f}s 小于两端余量之和")
        if not near_frame_boundary(tin, fps):
            add(WARN, "W2", f"第 {i} 段 in={tin:.3f} 不在 {fps:g}fps 帧边界上")
        if not near_frame_boundary(tout, fps):
            add(WARN, "W3", f"第 {i} 段 out={tout:.3f} 不在 {fps:g}fps 帧边界上")

        rows.append(
            {
                "index": i,
                "note": seg.get("note", ""),
                "in": tin,
                "out": tout,
                "speed": speed,
                "src_dur": round(src_dur, 3),
                "out_dur": round(out_dur, 3),
                "out_start": round(total_out - out_dur, 3),
                "out_end": round(total_out, 3),
            }
        )

        if prev_out is not None and tin < prev_out - 1e-6:
            add(WARN, "W4", f"第 {i} 段源时间与上一段重叠（{tin:.2f} < {prev_out:.2f}），会重复用同一素材")
        prev_out = tout

    markers = [m for m in segments if isinstance(m, dict)]
    if len(markers) > 1 and any(
        float(m.get("speed") or 1.0) != 1.0 for m in markers
    ) and any(float(m.get("speed") or 1.0) == 1.0 for m in markers):
        add(WARN, "W5", "同一成片里混用变速与恒速段，字幕时间需按输出时间轴重算")

    captions = edl.get("captions") or []
    if not isinstance(captions, list):
        add(ERROR, "E6", "captions 必须是数组")
        captions = []

    prev_end = None
    for i, cap in enumerate(captions, start=1):
        if not isinstance(cap, dict):
            add(ERROR, "E7", f"第 {i} 条字幕不是对象")
            continue
        try:
            start = float(cap["start"])
            end = float(cap["end"])
        except (KeyError, TypeError, ValueError):
            add(ERROR, "E7", f"第 {i} 条字幕缺少合法的 start / end")
            continue
        text = str(cap.get("text", ""))
        if end <= start:
            add(ERROR, "E8", f"第 {i} 条字幕 end 不大于 start")
            continue
        dur = end - start
        n = char_count(text)
        cps = n / dur if dur > 0 else 0
        if cps > args.cps_max:
            add(ERROR, "E9", f"第 {i} 条字幕 CPS={cps:.1f} 超过 {args.cps_max:g}（{n} 字 / {dur:.2f}s）")
        if n > args.max_line_chars and "\n" not in text:
            add(WARN, "W6", f"第 {i} 条字幕 {n} 字未换行，超过单行 {args.max_line_chars} 字")
        if total_out and end > total_out + 1e-6:
            add(WARN, "W7", f"第 {i} 条字幕 end={end:.2f}s 超出成片总长 {total_out:.2f}s")
        if prev_end is not None and start < prev_end - 1e-6:
            add(ERROR, "E10", f"第 {i} 条字幕与上一条重叠（{start:.2f} < {prev_end:.2f}）")
        prev_end = end

    errors = [x for x in issues if x["level"] == ERROR]
    warns = [x for x in issues if x["level"] == WARN]

    if args.json:
        print(
            json.dumps(
                {
                    "source": edl.get("source", ""),
                    "fps": fps,
                    "segments": rows,
                    "total_output_seconds": round(total_out, 3),
                    "caption_count": len(captions),
                    "errors": errors,
                    "warnings": warns,
                    "ok": not errors,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1 if errors else 0

    print("=== EDL 校验 ===")
    print(f"源素材      {edl.get('source', '(未填)')}")
    print(f"画布        {edl.get('canvas', '(未填)')}  帧率 {fps:g}")
    print()
    print(f"{'#':>2}  {'入点':>7} {'出点':>7} {'速度':>5} {'源长':>6} {'输出':>6} {'输出区间':>15}  备注")
    for r in rows:
        print(
            f"{r['index']:>2}  {r['in']:>7.2f} {r['out']:>7.2f} {r['speed']:>5.2f} "
            f"{r['src_dur']:>6.2f} {r['out_dur']:>6.2f} "
            f"{r['out_start']:>7.2f}-{r['out_end']:<7.2f}  {r['note']}"
        )
    print()
    print(f"总输出时长   {total_out:.2f}s（{int(total_out // 60)}m{total_out % 60:.1f}s）")
    print(f"字幕条数     {len(captions)}")
    print()

    if not issues:
        print("结论        通过。可以进入渲染。")
        return 0

    print(f"问题        阻塞 {len(errors)} 条，告警 {len(warns)} 条")
    for x in errors:
        print(f"  [{x['level']}] {x['code']} {x['message']}")
    for x in warns:
        print(f"  [{x['level']}] {x['code']} {x['message']}")
    print()
    print("结论        " + ("有阻塞级问题，先改 EDL 再渲染。" if errors else "可渲染，但建议处理告警。"))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
