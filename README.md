# 剪辑手艺 / video-editing-craft

一个 Agent Skill：**只处理已有素材的后期**——把一堆口播和 B-roll 变成能发的竖屏短片。

## 它解决什么

| 场景 | 它做什么 |
|---|---|
| 口播重剪 | 体检 → 词级转写 → 删长静音/口头禅/重复 take → 按论点重排 → 字幕 → 响度 |
| 多素材叙事 | 素材盘点 → 场景边界 → 去重 → 按节奏曲线落轨 → B-roll → 调色 |
| 工艺修复 | 糊/抖/色偏/音量飘/字幕越界/比例错，一次只改一项 |
| 平台适配 | 9:16 跟踪重构 + 安全区 + 一条母版三平台导出 |

从零生成素材不归它管——交给生成类 skill。

## 目录

```
video-editing-craft/
├── SKILL.md                      八条铁律 + 四条工作流 + 平台参数 + 验收
├── references/
│   ├── craft-playbook.md         节奏曲线、切点合法性、J/L cut、字幕、调色、变速、拆片法
│   ├── pipeline.md               目录、ffprobe、EDL、单次编码、ASS、响度、QA 证据链、配方
│   └── sources.md                学了哪些开源 skill、吸收什么、故意没学什么
└── scripts/
    └─ edl_check.py               EDL/字幕校验器（纯 Python，不依赖 FFmpeg）
```

## 安装

```bash
git clone https://github.com/zhu080218/video-editing-craft.git
cp -r video-editing-craft/video-editing-craft ~/workspace/.user_skills/
```

## 核心信条

1. **不动源文件**，产物进 `edit/`。
2. **不切在词中间**，切点留 30–200 ms。
3. **EDL 先落地**，再渲染；改只改 EDL。
4. **只编码一次**，每多压一遍就偷一点画质。
5. **看渲染出来的成片**，不看源素材。
6. **字幕是最后的视觉操作**。

## 校验器

```bash
python scripts/edl_check.py --edl edl.json --fps 30 --cps-max 9
```

检查片段逆序/重叠/过短、帧边界、字幕重叠/CPS 超限/越界。退出码 1 表示有阻塞问题。

## License

MIT
