# 流水线与交付

> 本文件解决「怎么把决定变成成片，且能复查」。命令是模板，参数按素材实际值替换。

## 目录

1. 目录与命名
2. 体检
3. 转写与缓存
4. EDL 结构
5. 单次编码（核心）
6. 字幕（ASS）
7. 响度归一
8. 素材与代理
9. QA 证据链
10. 可复现配方
11. 工具路由与交接

---

## 1. 目录与命名

```
<源目录>/edit/
├── 00-probe/      体检 JSON
├── 01-transcript/ 词级转写（只生成一次）
├── 02-edl/        edit_decisions.json（唯一事实来源）
├── 03-assets/     字幕、封面、B-roll、音效
├── 04-preview/    720p 预览
├── 05-master/     1080×1920 定稿
├── 06-export/     多平台导出
└── 07-verify/     QA 收据（截图、时长比对、响度报告）
```

命名：`<片名>-<版本>-<画布>-<日期>.mp4`，例如 `teaser-v3-1080x1920-20261120.mp4`。版本号只在 EDL 变更时递增。

## 2. 体检

```bash
ffprobe -v error -show_entries \
format=duration,bit_rate:stream=index,codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,sample_rate,channels:stream_side_data=rotation \
-of json in.mp4 > 00-probe/probe.json
```

必看四项：
- `avg_frame_rate ≠ r_frame_rate` → 变帧率（VFR），先转恒定帧率再剪。
- `rotation = -90 / 90` → 竖拍视频，宽高按显示方向交换。
- 无音轨 → 提前决定是配乐还是配音。
- 时长 < 预期 → 素材可能未完整拷贝。

## 3. 转写与缓存

只跑一次，存 `01-transcript/words.json`，结构：`[{w, start, end}]`。所有下游决策只读这份：

- 静音判定：相邻词间隔 > 0.8s 候选删除
- 口头禅：正则匹配（嗯/啊/那个/就是说/然后呢）
- 重复 take：连续 8 个词以上高度相似 → 只留后一条
- 字幕：按语义断句，不按标点硬切

素材变更时（换源文件）才允许重转写，并在 EDL 里记 `transcript_version`。

## 4. EDL 结构

```json
{
  "source": "in.mp4",
  "fps": 30,
  "canvas": [1080, 1920],
  "transcript_version": "words-v1",
  "segments": [
    {"in": 1.20, "out": 4.80, "note": "hook", "speed": 1.0},
    {"in": 6.10, "out": 9.30, "note": "point-1", "speed": 1.0}
  ],
  "captions": [
    {"start": 0.00, "end": 2.40, "text": "先说结论"}
  ]
}
```

规则：`in/out` 用源时间；段与段按输出顺序排列且不重叠；`speed` 影响输出时长（`(out-in)/speed`）。渲染前用 `scripts/edl_check.py` 校验。

## 5. 单次编码（核心）

切、拼、字幕、响度、封面全部放进一条命令。多段拼接用 `filter_complex` 的 `trim/atrim + concat`：

```bash
ffmpeg -y -i in.mp4 -filter_complex "
[0:v]trim=start=1.20:end=4.80,setpts=PTS-STARTPTS,scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30[v0];
[0:a]atrim=start=1.20:end=4.80,asetpts=PTS-STARTPTS,afade=t=in:st=0:d=0.03,afade=t=out:st=3.57:d=0.03[a0];
[0:v]trim=start=6.10:end=9.30,setpts=PTS-STARTPTS,scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30[v1];
[0:a]atrim=start=6.10:end=9.30,asetpts=PTS-STARTPTS,afade=t=in:st=0:d=0.03,afade=t=out:st=3.17:d=0.03[a1];
[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a];
[v]ass=03-assets/sub.ass,format=yuv420p[vo];
[a]loudnorm=I=-14:TP=-1.0:LRA=11[ao]
" -map "[vo]" -map "[ao]" \
-c:v libx264 -profile:v high -b:v 10M -maxrate 12M -bufsize 20M -g 60 \
-c:a aac -b:a 192k -ar 48000 \
-movflags +faststart 05-master/output.mp4
```

要点：

- **不要** `-c copy` 做精确切点：它只会对齐到关键帧，边缘出现黑帧或音画错位。
- 用**固定码率**而非 `-q:v`：跨编码器行为一致，文件大小可控。
- 变速从源素材直接做：`setpts=PTS/1.25` 配 `atempo=1.25`，不要从已编码版本再压一遍。
- `fps=30` 放在每段里，混帧率素材才不会在拼接时崩。
- 封面：`-ss <t> -frames:v 1 cover.jpg`，单独一次，不进主渲染。

## 6. 字幕（ASS）

用 ASS 而不是 SRT：能控字号、描边、位置、逐词组动画。

```ass
[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,Source Han Sans SC,56,&H00FFFFFF,&H00101010,&H80000000,-1,3,0,2,60,60,340,1
```

- `MarginV=340` ≈ 底部留 20% 安全区（1920 的 17.7%）。
- 中文断句按语义，一屏 6–9 字，超过 14 字必须拆。
- 字幕生成后跑一次 CPS 检查（`edl_check.py`）。
- 字幕时间用**输出时间轴**；先在 EDL 上算好偏移，再生成 ASS。

## 7. 响度归一

单遍 `loudnorm` 够用；要求严谨时两遍（第一遍测量，第二遍应用）：

```bash
ffmpeg -i 05-master/output.mp4 -af loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json -f null -
# 读取输出里的 measured_* 值，再带参数跑第二遍
```

验收：-14 LUFS ±1，真峰 ≤ -1 dBTP，长静音段不超过 2 秒。

## 8. 素材与代理

- 素材 > 50GB 或 4K 时，先建 720p 代理用于分析和预览，最终从原片渲染。
- 代理命名 `proxy-<原名>.mp4`，与源同目录，避免混用。
- 多素材先统一：分辨率、帧率、采样率、色彩空间（SDR/BT.709），再进时间线。

## 9. QA 证据链

交付前必须留下三类证据，放在 `07-verify/`：

1. **切点抽帧**：每个切点前后各 1 帧截图，确认没有黑帧/重复帧。
   ```bash
   ffmpeg -ss <t> -i 05-master/output.mp4 -frames:v 1 07-verify/cut-<t>.jpg
   ```
2. **时长比对**：`ffprobe` 输出的时长 vs EDL 计算总时长，偏差 ≤ 0.1s。
3. **响度报告**：`audio_master_report` 类的输出（LUFS / true peak / LRA）。

再加一条人工项：1× 带声完整看一遍。看不完的片子，观众也不会看完。

## 10. 可复现配方

把「已审的渲染配置」固化成配方：画布、码率、字幕样式、响度目标、切点规则。下一批素材直接套配方，只改 EDL。

配方字段示例：

```json
{
  "name": "kepu-60s-v1",
  "canvas": [1080, 1920],
  "fps": 30,
  "video": {"codec": "libx264", "bitrate": "10M", "maxrate": "12M", "gop": 60},
  "audio": {"codec": "aac", "bitrate": "192k", "samplerate": 48000, "lufs": -14},
  "caption": {"font": "Source Han Sans SC", "size": 56, "margin_v": 340, "cps_max": 9},
  "rules": {"min_seg": 0.3, "padding": 0.05, "max_transitions": 2}
}
```

## 11. 工具路由与交接

| 场景 | 用什么 | 为什么 |
|---|---|---|
| 精确切点、拼接、字幕、响度 | FFmpeg | 确定、可脚本化、单次编码 |
| 复杂动效、模板化批量 | Remotion / HyperFrames | 代码即时间线，能复用到 N 条 |
| 需要人工在软件里继续改 | 导出 OTIO / FCPXML / Premiere XML | 保留轨道与切点，不丢结构 |
| 交给剪映（CapCut）草稿 | 生成草稿 JSON 或走剪映自动化工具 | 国内分发最常见；注意草稿格式随版本变 |
| 逐帧修图式重调 | DaVinci Resolve（有 MCP 桥） | 调色与套底的工业标准 |

交接原则：**先交付「时间线 + EDL」，再交付成片**。只给 mp4，客户改一个字就得重剪一遍。
