# proteus844

**把数字逻辑作业里的电路图，变成可以直接仿真、交作业的 Proteus 工程。**

拍张照片、截个图、或者照着实验指导书画的草图 —— 交给这套工具，输出一个
`.pdsprj`：器件摆好、线连好、电源符号挂好，打开就能跑仿真、看波形、交作业。

> 面向课程：**数字逻辑 / 数字电路实验**（组合逻辑、编码器、译码器、计数器那一类）。
> 典型场景：作业要求"画一个 3 人表决器"/"画一个 74LS147 编码器"，你手上只有一张图。

---

## 当前版本

| | |
|---|---|
| 本工具 | **v1.1.0** |
| 实测 Proteus | **8.15，FILEVER 844** |
| 代码层面支持 | FILEVER **840 / 844 / 847**（三套模板布局都有分支） |
| 实测电路 | 图 1.1 组合逻辑（9 器件）、74LS147 编码器（22 器件） |

### v1.1.0 改了什么

**布线层（`route/`）**
- 导线不再压着引脚线走（引脚内侧设为禁行区，实测 6 处 → 0）
- 列间距按引脚外伸量 + 穿网数计算 —— 之前 7400 输入脚外伸 5 格、
  源输出 2 格，中间只剩 2 格通道，三条网挤不下会被推到器件内部
- 走廊按「交叉×3 + 线长×0.15」择优
- 修掉 80 个随机电路里 12 个「完全无法走线」
- 串联链竖排：`RES` 转 270（1 脚在上、朝上），R 底脚直落 LED 阳极

**美观（`beautify/` 新模块）**
- `center()`：按器件本体 + 导线的真实外框整格平移，摆到图纸正中
- `review()`：偏移 / 留白 / 绕线系数 / 跨网共线 + **0~100 观感分**
- 命令行：`python -m proteus844.cli review 工程.pdsprj --donor donors/base.pdsprj`

**校验（`verify/connection.py` 新模块）**
- 导线端点分四类：落在引脚 / 与别的线共端点 / 电源端子桩 / **悬空**
- 修掉旋转器件被误报悬空的双重旋转问题

**版本（`version.py` 新模块）**
- `python -m proteus844.cli probe 工程.pdsprj` → RELEASE / FILEVER / CDB 版本
- 未知版本给可操作提示，不再抛原始 traceback

**其它**
- `writer` 支持 `label_offsets`（竖放电阻的数值不再压在器件上）
- `validate` 提前拦：位号必须含数字、单网最多 4 脚（星形结点上限）
- `cli assemble` 保留 `terminals`（原来硬写成 `[]`，GND 会丢）

### 版本兼容性怎么判断

Proteus 工程的版本号写在 `PROJECT.XML` 的 `<TIMESTAMP FILEVER="...">` 里。
拿到一个别人的工程，先看这个值：

```bash
python -m proteus844.cli donors          # 会列出每个 donor 的器件数
python -m proteus844.symbol_table donor.pdsprj   # 能读出来就说明版本兼容
```

- **FILEVER 840 / 844 / 847** → 可以用
- **其它版本**（815 之前的老版、9.x 新版）→ 大概率不行。先拿一个小工程试，
  能 `symbol_table` 读出来才算兼容；读不出会直接报 `Requires the verified FILEVER ... template layout`

---

## 不同情况下怎么适应

### 情况 1：你的 Proteus 不是 8.15

**最省事的办法：不要换 Proteus，换 donor。**
donor 就是从**你自己的 Proteus** 里存出来的一个空工程（或含几个器件的工程）。

```bash
# 在你自己的 Proteus 里新建工程 → 放几个要用的器件 → 存成 my.pdsprj
python -m proteus844.cli donor-add my.pdsprj     # 登记成 donor
python -m proteus844.symbol_table my.pdsprj      # 验证能读出来
```

只要 `symbol_table` 能读出器件表，版本就兼容。

### 情况 2：要用的器件不在 donor 里

**donor 里没有的器件画不出来** —— 这是硬限制（我们靠 donor 里的符号模板生成图形）。

```bash
python -m proteus844.cli donors                      # 看现有 donor
python -m proteus844.symbol_table donors/base.pdsprj # 看某个 donor 有哪些器件
```

| donor | 含 |
|---|---|
| `base.pdsprj` | 7400 / 7410 / 7404 / RES / LED-RED / LOGICSTATE |
| `kit.pdsprj` | 7404 / 74147 / 7430 / 7448 / 7SEG-COM-CATHODE / BUZZER / RES / SW-SPST |
| `kit_spdt.pdsprj` | kit + 三端开关 SW-SPDT |

缺什么，就在 Proteus 里放一个、存盘，再用 `donor-add` 登记。

### 情况 3：电路小（≤10 个器件）

**用自动布局，最省事**：

```bash
python -m proteus844.cli assemble comps.json nets.json out.pdsprj --donor donors/base.pdsprj
```

`comps.json` 只需要器件型号，**不用坐标**：

```json
[{"ref":"LS1","device":"LOGICSTATE","value":"0"},
 {"ref":"U1:D","device":"7400","value":"7400"},
 {"ref":"U4:A","device":"7410","value":"7410"}]
```

### 情况 4：电路大（十几到二十几个器件）

**先直接跑自动布局，别急着手动摆。** 实测（7400 串联 + 末级 LED）：

| 器件数 | 结果 | 观感分 |
|---|---|---|
| 9 / 13 | ✓ 零悬空 | 100 |
| 17 / 21 / 25 | ✓ 零悬空 | 78~100 |

22 器件的编码器也能全自动（观感 70 分，交叉多但电气正确）。

**真正画不出来的只有一种**：一条网连 5 个以上引脚 ——
星形结点只支持 2~4 根线。`validate` 会提前拦下并提示拆成两级。

需要精确控制位置（功能块、信号流向要和图纸标注一致）时才自己给坐标：

```python
comps = [{"ref":"SW1","device":"SW-SPST","value":"SW","x":-40,"y":28,"rotation":0}, ...]
doc = plan_route({"components":comps,"nets":nets}, donor)
build({"components":comps,"nets":nets}, doc, donor, out)
```

> ⚠ **Proteus 的页框以中心为原点**（x∈±W/2，y∈±H/2）。
> 全放在正坐标会整块贴到右下角并越出图框。自己给坐标也要居中。
> 另外：**引脚不一定在整格上**（7SEG 的 COM 在 -10.5 格），
> 坐标别自作主张取整，否则线会差半格、看着像没接上。

### 情况 5：图是扫描件/照片，想自动识别

**目前不行**，识别那一步要人（或 AI）看图。

- 工具能帮：`pin_hints` 放大标注引脚编号、`check_against_image` 挑出可疑的网
- 工具不能：把像素自动变成"谁连谁" —— 跨符号族的比例差异（同一张图上 2.2~8.8 倍）让几何匹配不成立

实践路径：**你看图说出"谁连谁"，工具负责画。**

---

## 快速开始

```bash
# 0) 自检（10 项，约 12 秒）。不通过就别往下走。
python -m proteus844.selftest

# 1) 看 donor 里有什么
python -m proteus844.cli donors
python -m proteus844.symbol_table donors/base.pdsprj

# 2) 写 comps.json + nets.json（器件型号 + 谁连谁）
# 3) 生成
python -m proteus844.cli assemble comps.json nets.json out.pdsprj --donor donors/base.pdsprj

# 4) 验收：在 Proteus 里点「工具 → 编译网络表」，导出 SDF
python -m proteus844.verify.netdiff nets.json out.SDF

# 5) 体检「画得好不好」
python -m proteus844.cli review out.pdsprj --donor donors/base.pdsprj
```

**迭代只在命令行做（0.3 秒一轮）。** 只有最后确认才开 Proteus 出 SDF、看渲染。

---

## 画得好不好：观感分

`beautify` 模块负责这件事 —— **设计完之后把整张图摆到图纸正中，并给一个分数**。

```bash
python -m proteus844.cli review out.pdsprj --donor donors/base.pdsprj
```

```
外框 70×28 格，占纸 70%×40%，观感分 100/100
  留白 左15 右15 上21 下21
  偏移 +0.0, +0.0 格；绕线系数 1.01
  ✅ 居中、在纸内、无跨网共线、绕线正常
```

它查四件事：

| 指标 | 含义 |
|---|---|
| **偏移** | 整块的中心离图纸中心多远（Proteus 页框以 (0,0) 为中心） |
| **留白** | 四边各剩多少格；负数就是越出图框 |
| **绕线系数** | 实际导线总长 ÷ 最少需要的长度；1.0 是笔直，>1.8 就是绕远路 |
| **跨网共线** | 两个不同的网画在同一条线上，看着像连在一起 |

流水线会**自己试几种摆法（含折列）取分数最高的那个**，并把分数打出来：

```
[2] 折列 6 间距 8/6 → 90×28 格，观感 72/100
[2.7] 采用折列 6 间距 8/6（观感 72/100）→ 验收 {'OK': 28, 'SHORT': 0, 'BROKEN': 0}
```

实测：图 1.1（9 器件）100 分；编码器（22 器件）从 122×212/24 分优化到 **104×46/70 分**。

## 它怎么保证画对了

| 手段 | 能证明什么 | 不能证明什么 |
|---|---|---|
| `build` 后文件级重建 | 画的和声明的网表一致 | **画的和原图一致**（自证） |
| **Proteus 编译的 SDF** | **真实电气连接** ← 唯一真值 | 观感 |
| `screenshot_check` | 本视口内无斜线 | 全图（跟视口有关） |
| `plan.check` | 布线无冲突、无静默短接 | 线好不好看 |

**验收只认 SDF。** 一张好看但错的图，比一张丑对的图危险得多。

---

## 已知限制

- 识别要人参与（见情况 5）
- 自动布局适合 ≤10 器件
- 密集扇出区可能留 1~2 处共线重叠（不影响电气）
- 三端开关目前用两脚近似（行为等价，静止时输入靠 Proteus 的高电平默认）
- 奇数偏移的引脚挂不上电源符号（`SW-SPDT` 的掷端就是），所以 SPDT 只能接一个掷

---

## 目录

```
proteus844/
  BRIEF.md      给别人/子代理用的自足任务书（一句话派活）
  README.md     本文件
  cli.py  server.py  pipeline.py  selftest.py  version.py
  recognize/    图片 → 线段 / 结点 / 引脚提示
  netlist/      线段 → 网表
  route/        布局(place/template) / 布线(plan) / 度量(metrics)
  beautify/     居中 / 观感体检 / 评分（v1.1 新增）
  build/        写 .pdsprj（wirelabel 是失败尝试，已禁用）
  verify/       SDF / 文件 / 结构 / 截图 / 图纸 / 初筛 / 端点(connection)
  skill/SKILL.md  作业手册（所有踩过的坑都在这）
  donors/       供体工程（器件模板来源）
  tests/        回归 + 用例
  experiments/  走不通的路（负面记录）
```

## 已知的坑（都写在 SKILL 里，这里只列最要命的）

- **连线标号（A/B/C）写不了** —— 手工拼字节会让工程损坏，SKILL §3.8
- **电源/地端子必须显式声明**，否则那根脚是孤立单脚网，SKILL §3.10
- **引脚不一定在整格上**（7SEG 的 COM 在 -10.5 格），别自己取整，SKILL §3.6
- **一列器件太多要折列**，否则拉成面条，SKILL §3.4

## 许可

本工具 MIT。`vendor/ref844/` 来自 **proteus-automatic-api 0.2.0**（MIT），
本项目对它有一处修改，详见 [NOTICE](NOTICE)。

仓库**不含**任何教材扫描图（版权原因）。依赖示例图的测试在缺图时自动跳过。
