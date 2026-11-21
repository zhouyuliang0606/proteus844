---
name: proteus844
description: >
  Draw a schematic into a real Proteus 8 project (.pdsprj) from an image, a
  document, or a plain description. Recognises components and wiring, plans the
  routing, builds the file, and verifies it against Proteus's own compiled
  netlist. Trigger words: 原理图, 电路图, 画电路, 照着图画, 识别电路, 网表, Proteus,
  pdsprj, ISIS, schematic, circuit diagram, netlist, draw this circuit.
description_zh: 原理图识别 → 布线规划 → 生成 Proteus 工程 → 网表验收
version: 2.0.0
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
---

# 原理图 → Proteus 工程

**要交给别人/子代理做？** 让对方读包根目录的 BRIEF.md —— 那是自足的任务书，
一句话就能派活：「读 <包>/BRIEF.md，按它做，图在 <路径>」。

**分工**：工具做确定的事，你只做判断和选择。重活都在 `proteus844` 里，
**不要自己重写切图、找线、建网、布线算法**。

```
图片/文档/文字 ──识别──> 网表 ──plan_route──> 布线方案 ──build──> .pdsprj ──verify──> 结论
```

## 0. 先确定工具从哪来（两条路，功能等价）

**先跑自检**（10 项，约 12 秒）：

`ash
python -m proteus844.selftest          # 全部
python -m proteus844.selftest --fast   # 跳过慢项
`

它会把 MCP 工具、CLI、文档一致性、端到端链路、识别链路、总回归全跑一遍。
不通过就先别往下走 —— 后面的坑都建立在它之上。

**A. MCP 路线**（推荐）—— 需要先注册，否则敲工具名会直接失败：

```json
{"mcpServers": {"proteus844": {
  "command": "<python 绝对路径>",
  "args": ["-m", "proteus844.server"],
  "cwd": "<解压后的上级目录>"}}}
```

`python -m proteus844.cli init` 会按本机实际路径打印这段配置。

**B. 命令行路线**（不用注册）：`python -m proteus844.cli <子命令>`

### 名字对照（本文件用 MCP 名，CLI 是另一套）

| 要做什么 | MCP 工具 | CLI |
|---|---|---|
| 看 donor 的器件/引脚 | `donor_info` | `donors`（只列表） |
| 符号尺寸表 | `symbol_table` | — |
| 图→线段 / 结点 | `recognize_segments` / `recognize_junctions` | `seg` / `junc` |
| 线段+结点+引脚尖→网表 | `trace` | `trace` |
| 校验网表 | `validate_netlist` | 内含在 `build` / `draw` |
| 算布线 | `plan_route` | `build` 默认自动算 |
| 写工程 | `build` | `build` |
| 一键（图→工程） | `draw` | `draw` |
| 已有网表→工程 | — | `assemble` |
| 文件级验收 | `verify_file` | `verify-file` |
| 结构读回 | `verify_structural` | `verify` |
| 引擎级验收 | `verify_netdiff` | `verify/netdiff.py` |
| 识别校验 | `verify_recognition` | — |
| 可读性 | `check_overlap` | — |

**只有 MCP 路线有全部 14 个工具。** 走 CLI 时缺的那几项，用 Python 直接调模块
（如 `from proteus844.verify import file_netlist`）。

## 0.5 每次都先做

| 步骤 | 工具 | 为什么 |
|---|---|---|
| 1 | `donor_info(donor)` | 确认目标器件在供体里，**并拿到真实引脚名** |
| 2 | `symbol_table(donor)` | 拿到引脚偏移和尺寸，用于比例换算和布线 |

供体（donor）是一个 `.pdsprj`，器件定义都从它来。
**目标器件不在供体里 → 停手**，让用户在 Proteus 里放一个该器件、存盘，再用那个工程当 donor。
不要试图从 `.LIB` 库文件里取定义。

### donor 里有内容没关系（但会干扰排查）

工具只从 donor 取**器件模板**。实测：donor 里那 14 个器件 / 53 条导线
**不会**出现在输出里（输出正好是我们的 22 个器件）。

但 donor 太杂时会误导判断 —— 早期我们把画面上的异常归咎于"donor 带进来的旧图"，
查了两小时才发现不是。`donor_check` 只作体检用，不用为了它专门清空 donor。

## 1. 网表结构（唯一的中间表示）

```json
{
  "components": [
    {"ref": "U1:D", "device": "7400", "value": "7400", "x": 7, "y": 0}
  ],
  "nets": [{"name": "A", "pins": [["LS1","Q0"], ["U1:D","A"], ["U3:B","B"]]}],
  "terminals": [{"kind": "ground", "name": "GND", "pin": ["D2","K"]}]
}
```

- `x / y` 单位是**格**（1 格 = 100 mil = 254000 native），**y 轴向上**（Proteus 惯例）。
  从图片像素换算时 y 要取反：`grid_y = -pixel_y / px_per_grid`
- **电源/地写成 `terminals`，不要建成一条叫 `VCC` 的 net**。每项形如
  `{"kind": "ground"|"power", "name": "GND", "pin": ["U7","D"]}` —— 它会在该引脚挂一个符号，
  `build` 会自动把同名的芯片电源脚并到同一网络
- **未连接的引脚直接不写进 `nets`**（例如原图里悬空的 74147 Q3）。
  `validate_netlist` 不会因此报错，`verify_netdiff` 会把它显示成单脚网 —— 那是正常的
- `pin` 必须填**符号引脚名**，不是图上印的脚号 —— 见下
- `terminals[].kind` **必须小写**：`ground / power / input / output / bidir / label`

### ⚠ 引脚名 ≠ 脚号

```
图上印的（框外数字）: 13 / 12 / 11
符号里真正的名字    : A  / B  / Y      ← 网表里写这个
```

多单元器件更要注意：7400 四个门，同样是 A/B/Y，脚号完全不同
（A单元 1/2/3、B单元 4/5/6、D单元 13/12/11）。**脚号表不能复用。**

**判据**：按符号上的上下位置定 —— 上面的输入 = A，下面的输入 = B，输出 = Y；
三输入门从上到下 = A/B/C。脚号只用来判断"这是哪个单元"。

写完网表先跑 `validate_netlist`，它会当场指出哪个引脚名不对。

## 2. 从图片识别

图的分辨率通常很小（几百像素宽），**直接看必错**。按顺序来：

1. **放大切块**：自己写脚本放大 6~12 倍，按区域切块后逐张看
2. `recognize_segments(image)` → 所有横竖线段的精确端点
3. `recognize_junctions(image)` → 实心结点，**带 EDT 峰值**
4. **认器件**：型号（图上印的字符）、位号、本体包围盒 `(x0,y0,x1,y1)`
5. **定引脚尖**：线段端点里挑出对应每个引脚的坐标
6. `plan_route` / `build` / `verify_netdiff`

### 引脚尖坐标怎么拿（不要靠眼睛量）

用 `pin_hints`：给它一个器件框，它返回一张**放大标注图**和一张**编号坐标表**。

```bash
python -m proteus844.cli hints 图.png --bbox 558,167,582,177 --out R1.png --scale 12
# MCP: pin_hints(image, bbox, out_png, scale=8)
```

输出长这样（坐标是**原图**像素）：

```
 1:(558.0,168.5)   2:(582.0,168.5)   3:(558.0,172.0)   4:(582.0,172.0)
 5:(594.0,172.0)   6:(562.3,175.0)  ...
```

图上是 10 倍放大的裁剪，每个导线端点画红圈标号，器件框是蓝框。
**你只要说"引脚 1 是 3 号"，不用再量像素。**

实测编码器 22 器件 / 80 个真引脚，**75% 的真引脚坐标直接出现在表里**。
剩下 25% 多半是本来就没接线的脚（比如 74147 的 Q3）或抽取缺口 ——
表里找不到，就说明这根脚附近没有导线，回去确认是不是真空脚。

### 关键：引脚尖几乎总在线段端点上

`recognize_segments` 给出的是**精确坐标**，所以"读引脚号"这步能省掉大半 ——
你只需要判断"哪个端点对应哪个脚"，不用量像素。

### ⚠ 浅灰线会被默认阈值漏掉

默认二值化阈值 **140** 只抓深色线。实测一张教材图：开关的三条信号竖线、
数码管的 F/G 引线、被文字压住的输入行**全丢**，导致这些器件整只悬空。

发现某器件莫名悬空时，调高阈值重抽：

```bash
python -m proteus844.cli seg 图.png --threshold 200 --min-len 6 --out segs.json
# MCP: recognize_segments(image, threshold=200, min_len=6)
```

`min_len` 也要降 —— 阶梯走线的短竖线常常只有 5~8px。

### 引脚尖取哪里（必须统一）

`verify_recognition` 对这个**极度敏感**：同一份 components.json，
取"引线外端"得 26/68 不一致，取"符号体边"得 14/68。

**约定：取导线真正接触的那一点** —— 线段端点里离符号体最近的那个，
不是符号外框的角，也不是引线的另一端。拿不准就放大到 20× 逐像素看。

### 结点（peak 值只作提示）

- **≥2.1** → 实心结点（真连接）
- **≈2.0** → 可能是门输出的小圆圈，**也可能是数字笔画压在线上**。
  实测有图里两个 peak=2.00 的点其实是脚号 `2` 的笔画。
  → **必须回图上看一眼**，别按阈值一刀切

### 器件本体不是导线

器件的矩形边框、圆弧也会被抽成线段。`plan_route` / `trace` 支持传器件包围盒把它们排除。
判据是"两端都在盒内**且**都不接引脚尖"，接引脚的容差要**紧（1px）** ——
本体侧边常常离引脚尖只差 2~3px，用 3px 会误判成引线，把器件两端短接。

### 比例（只在需要精确坐标时用）

```
px_per_grid = 图上某器件引脚尖跨度(px) / symbol_table 里对应的格数
```

拿**引脚尖跨度**去除，不是本体方框。换两三个器件各算一次，比值应一致。
比例偏差 >1 格时，引脚会吸附到错误的线段端点上。

## 2.5 双路识别 + 核对（复杂图必用）

图越复杂，单次识别越容易看错。**开两路独立识别，然后机器比对**，比任何一次单独的
“我觉得对”都可靠。代价是 token 翻倍，**只在器件超过 10 个、或要求高可靠时用**。

### 做法

1. **主路**：你自己按第 2 节做完识别，得到 `netlist_main.json`
2. **副路**：起一个子代理，**只给它图和 donor，不给你的结果**，让它独立产出
   `netlist_sub.json`
3. **机器比对**：把两份网表按"网络的引脚集合"对齐，只看差异
4. **只核对差异**：两份一致的不用管；不一致的回原图放大看，定谁对
5. 合并成最终网表，再进布线

### 子代理提示词模板（照抄，把尖括号换掉）

```
任务：把一张原理图独立识别成网表。不要参考任何已有结果。

准备：解压 <包路径> 到临时目录；只在那里工作，不要改原目录。
必读：<包>/skill/SKILL.md 第 2 节；<包>/README.md
图：<图片绝对路径>
供体：<包>/donors/<donor>.pdsprj —— 先跑 donor_info 看真实引脚名
产出：
  1) components.json  [{"ref","device","bbox":[x0,y0,x1,y1],"pins":{"名":[x,y]}}]
     （引脚尖用像素坐标，尽量给全）
  2) netlist.json     {"components":[...],"nets":[{"name","pins":[[ref,pin],...]}]}
  3) log.md           判断日志
要求：位号/型号是图上印的还是你猜的，标出来；看不清就写清楚，不要编；
      引脚读不出来就省略并说明。只识别，不要画图，不要启动 Proteus。
```

### 比对脚本（照抄）

```python
import json
a = json.load(open("netlist_main.json"))["nets"]
b = json.load(open("netlist_sub.json"))["nets"]
key = lambda n: frozenset(tuple(p) for p in n["pins"])
A = {key(n): n["name"] for n in a}
B = {key(n): n["name"] for n in b}
for k in A.keys() - B.keys():
    print("只在主路:", A[k], sorted(k))
for k in B.keys() - A.keys():
    print("只在副路:", B[k], sorted(k))
```

### 判定原则

| 情况 | 处理 |
|---|---|
| 两路一致 | 直接采信，**不用再看图** |
| 一路多一个引脚 | 回图放大看那个引脚到底连没连 |
| 两路的分组不同 | 一定有一路把某条线看错了，回图看那条线的**两端** |
| 两路都说不清 | 标成未决项交给用户，不要猜 |

**两条都错但错得一样**的情况存在（比如都漏了同一根灰线），所以还要配第 4 节的渲染核对。

## 3. 布线

`plan_route(netlist, donor)` 会算好：两脚网的正交折线、多脚网的星形结点、通道分配。
**先让它算，再判断好不好看**，不要自己写坐标。

它遵守的规则（改参数时按这个想）：

| 规则 | 说明 |
|---|---|
| 跨度降序 | 跨得最远的网用最外侧通道，否则会横穿所有别的线 |
| 通道间距 ≥2 格 | 太近会被看成一条线 |
| 引脚出线方向 | 折线必须从引脚朝向那侧出去，否则 Proteus 报 `ROUTE_ENDPOINT_OFF` |
| 不回折 | 同一段不能来回走，否则 `Repeated wire vertex` |

**器件间距直接决定能不能布线**（早期文档写的"挪器件没用"是错的，已更正）：

| 电阻间距 | 结果 |
|---|---|
| 1 格 | `完全无法走线（无合法正交路径）` |
| 3 格 | 能布线，只剩 2 处共线重叠 |

所以 `plan_route` 会**自己把挨太近的引脚推开**（`separate_pins`），并把挪动后的坐标
写在返回值的 `components` 里；`build` 会优先采用这份坐标，**两步之间不要自己再改**。

另外：`plan_route` 的 `ok=false` 只表示**有观感问题**（平行间距 / 共线重叠，不会连通）。
返回值里的 `plan` 仍然可用 —— **但绝不能不带 plan 去 build**（见第 4 节）。

## 3.4 器件多了就别用自动布局

**实测：22 器件的编码器图，uild_from_topology 给的是 120×224 格**（A4 只有 100×70），
像一条面条。试过按图纸高度折行，结果变成 360 宽、还把布线堵死（网 N27 完全无法走线）。

**结论**：自动布局适合 **≈10 个器件以内**。再多就自己给坐标：

`python
comps = [{ref: SW1, device: SW-SPST, value: SW,
          x: -40, y: 28, rotation: 0}, ...]   # 记得居中（页框以原点为中心）
doc = plan_route({components: comps, nets: nets}, donor)
build({components: comps, nets: nets}, doc, donor, out)
`

摆位套路（按信号流左→右）：开关/源 → 输入芯片 → 中间门 → 输出芯片 → 限流电阻 → 显示器/负载。

## 3.5 只给拓扑就能画（推荐路线）

**AI 不需要输出任何像素坐标。** 认清楚「有哪些器件」和「谁连谁」，剩下的交给工具：

`
图 → 你：器件清单 + 网表（谁连谁）  →  工具：布局 + 布线 + 写入 + 验收
`

`ash
python -m proteus844.cli assemble comps.json nets.json out.pdsprj --donor donors/kit.pdsprj
# comps.json 只要 ref / device / value，没有 x/y
`

`python
build_topology(netlist, donor, out)     # MCP
pipeline.build_from_topology(...)       # Python
`

工具会做：
1. 把 VCC/GND 这类网转成电源端子（十几脚的星形是画不出来的）
2. 分层布局：输出脚 → 输入脚建图，最长路径分层，源在左汇在右，层内按重心排序
3. 间距不够就自动加大重试
4. 布线 → 写盘 → 文件级验收
5. 图纸按内容自适应

**实测**：图 1.1（9 器件）→ 78×42 格、8/8 OK；
编码器（22 器件）→ 120×224 格、28/28 OK。两张都是**只给拓扑**画出来的。

**这条路的好处**：AI 只做它擅长的认器件、认连接，
不再碰量像素、定坐标这种它必然出错的事。


## 快环 / 慢环（别把 1 秒的事做成 5 分钟）

| 环 | 用什么 | 耗时 | 查得出什么 |
|---|---|---|---|
| **快环** | python -m proteus844.cli assemble ... | **0.3~2 秒** | 布局尺寸、布线冲突、文件级验收、图纸自适应 |
| **慢环** | 开 Proteus + 编译 SDF + 截图 | 1~3 分钟 | 引擎级真值、渲染观感 |

**迭代只在快环里做。** 改布局、调间距、修布线，全用 ssemble 或 plan.check + erify_file，
**不要每改一次就开 Proteus 截图**。开 Proteus 只做两件事：

1. 最后出一次 SDF 做权威验收
2. 最后看一次渲染，确认观感

截图也要省着用：**裁局部放大**看关键区域，不要整屏读大图。

## 3.6 画图美观（beautify）

**布局只决定"信号从左到右"，不决定"整块摆在纸的哪"。** 这一步单独做。

```python
from proteus844 import beautify as B
B.center(doc, donor)                       # 设计完 → 摆到图纸正中
r = B.review(doc, donor, sheet=(132, 70))  # 体检
print(B.format_review(r))
```

**对已经写好的工程也能体检**：

```bash
python -m proteus844.cli review out.pdsprj --donor donors/base.pdsprj
```

四项指标（`review()` 返回同名字段）：

| 字段 | 判断标准 |
|---|---|
| r["offset"] | 应在 ±1 格内。超了说明没居中 |
| r["margins"] | 四边留白，任一为负 = 越出图框 |
| r["detour_ratio"] | 实际线长 ÷ 最短需求。<1.3 好，>1.8 绕远 |
| r["cross_net_overlaps"] | 跨网共线处数，看着像连在一起 |

r["score"] 是 0~100 的综合分，**只用于横向比较两版哪版更好**，不是绝对标准。

### 摆不下怎么办

`place()` 有三个旋钮，`build_from_topology` 会自动组合试一遍取最高分：

- `sheet=(132,70)` → 自动收缩间距，能装下才缩
- `max_per_col=6` → 一列超过 6 个就折到右边新列（20+ 器件必须用）
- `gap_x / gap_y` → 显式间距

**关键坑**：行距若取全局最大器件高度，一个高器件（数码管）会把每一行都撑开，
22 器件因此拉成 212 格高。现在按**每列自己**的器件尺寸算。

## 4. 验收（顺序不能改）

| # | 工具 | 判定 |
|---|---|---|
| 1 | `validate_netlist` | 引脚名/位号/器件都对得上 |
| 2 | `build(netlist, donor, out, plan=...)` | 写出文件 —— **plan 必须传**，见下 |
| 3 | **`verify_netdiff(netlist, sdf)`** | **唯一引擎级判据**：每条网都 OK 才算对 |
| 4 | `verify_structural` | 器件数、坐标 |
| 5 | 可选：`check_overlap` | 只影响可读性，**不是对错** |

### ⚠ 识别完先自检一遍（会误报，只看趋势）

```python
check_against_image(components, netlist, image)   # MCP
```

它用图上的线段几何判断：每条网声明的引脚在图上是同一个连通块吗？两条网会不会根本是同一条？
**能在没人看图的情况下抓出**：引脚标错位置、把不相干的脚凑成一条网、真网漏连。

**但它会误报**：实测正确网表在教材扫描件上仍有 ~24 条告警 ——
浅灰线没抽出来造成假断开，文字笔画压在导线上造成假连接。

**用法**：把它当"可疑清单"，逐条回图确认；**不要**当通过/失败的判据。
唯一的电气判据永远是 Proteus 编译出的 SDF。

### ⚠⚠ `plan` 必须传给 `build`，否则会静默产出短接

实测：同一个网表，`build(netlist, out)` 不带 plan → 返回 `ok:true`、文件也写了，
但 `verify_file` 报 **8 个 SHORT**（R2 并进 R4、R3 并进 R7）。传了 plan → **28/28 OK**。

不带 plan 时会退回 vendor 的自动布线，密集电路上会乱连。
CLI 的 `build` 和 MCP 的 `build` 现在都会在缺 plan 时自己算，**但显式传最安全**：

```python
plan = plan_route(netlist, donor)      # ok=false 也能用
build(netlist, donor, out, plan=plan)
```

`verify_netdiff` 需要 Proteus 编译出的 SDF —— **这一步没有包内工具**：
让用户在 Proteus 里点「工具 → 编译网络表」，或用 GUI 自动化 MCP 的 `proteus_netlist`。
没有 Proteus 时用 `verify_file`（文件级重建，抓得出生断和短接）。

### ⚠ 器件替换会改语义 —— 开关/按钮最容易翻车

donor 里没有的器件，换一个"看起来差不多"的会**改变电路行为**，而且所有几何验收都发现不了。

实测：原图 6 个开关是**三端 SPDT**（极点接 74147 输入，上掷接 VCC、下掷接 GND，
静止停在上掷）。donor 只有 `SW-SPST`（COM/NO），第一次接成了 `COM→VCC、NO→输入` ——
按下把输入**拉高**，而 74147 是**低有效**，所以永远不激活。

正确的两脚近似是 `COM→信号、NO→GND`：静止时输入悬空（Proteus 按高电平），
按下拉低，行为才和原图一致。

**规则**：
- donor 里没有的型号，先看**引脚数**是否一致；不一致就明确告诉用户"这个替换会丢功能"
- 开关类器件尤其要确认：**哪一端是公共端、哪一端接什么电平、有效电平是高还是低**
- 换完在渲染图上确认：电源/地符号出现在该出现的那一侧

### ⚠ 每条导线必须从「器件列表里更靠前」的一端开始记录

这是最容易毁掉整张图的一条，实测数据：

| 同一对引脚、同一条路径 | 斜线能量 |
|---|---|
| 起点 = 电阻（列表第 2 个） | **0.64** ❌ |
| 起点 = 7448（列表第 1 个） | **0.0009** ✅ |

只是把首尾对调，画面从"一片斜线"变成"完全正交"。
`build` 已经自动按器件顺序纠正，**手写 RoutePlan 时务必保持同样顺序**。

### ⚠ 必须看渲染图 —— 网表对了不等于画对了

实测过一次事故：网表 8/8 全对、`shorts: []`、零弹窗，但画面上一团三角形、
两个器件叠在一起。原因是 **rotation 没设对**、引脚还落在同一格。

`verify_netdiff` / `verify_file` **永远抓不到这类错** —— 它们只看电气连接。

所以生成后必须：

1. 跑 `verify_recognition`（逐引脚比对出线方向）—— 朝向错了这里会报
2. 看 `draw` 返回的 `layout_warnings`（器件重叠）
3. 截图肉眼确认：朝向对不对、有没有叠在一起、有没有奇怪的大绕行
4. 觉得不对就回 `components.json` 改 `rotation` / 位置，**不要只信网表**

**别试图用"图上线段 vs 画里导线的重合率"来验识别。** 实测过：正确和错误的图
重合率都是 ~48%，因为 Proteus 符号和教材符号比例不同、文字/标题/GND 符号又混在
线段里。逐引脚的**出线方向**才是符号无关、可判定的量。

### 三个认知纠偏

- **重叠 ≠ 短路**：Proteus 按导线端点判连接，几何上压在一起不会短接（实测过）
- **零弹窗 ≠ 画对**：打开成功只说明文件格式合法
- **网络表一致 ≠ 识别对**：生成用的就是识别结果，识别错了它照样一致。
  验证识别要靠**回图对照**或人看截图

## 5. 错误码 → 该做什么

| 码 | 恢复动作 |
|---|---|
| `DONOR_MISSING_DEVICE` | 让用户在 Proteus 里放该器件存盘，再用它当 donor |
| `PIN_NOT_IN_SYMBOL` | `donor_info` 查真实引脚名，别用脚号 |
| `REF_INVALID` | 位号改 `U1:A` 形式 |
| `ROUTE_ENDPOINT_OFF` | 折线端点要落在引脚尖上；检查出线方向 |
| `ROUTE_OVERLAP` | 改通道坐标，拉开 ≥2 格 |
| `ROUTE_UNROUTABLE` | 空隙不够，挪器件或手写 RoutePlan |
| `NET_BROKEN` | 有引脚没搭上线：多半是引脚取在段中间而不是端点 |
| `NET_SHORT` | 某网被并进更大的网：查跨网共线、或引脚插在别人线上 |
| `PROTEUS_REJECTED` | 记下弹窗原文，多半是 CDB 结构问题 |

## 6. 已知限制（别过度承诺）

- **器件只能来自 donor**。donor 里没有的型号，只能让用户先在 Proteus 里放一个。
- **奇数偏移的引脚挂不上电源终端**。终端附着点按 2 格对齐，`SW-SPDT` 的掷端偏移是
  `(3,-1)`（奇数），`add_terminal` 会报 `Pins share the same bus attach`。
  实测：SPST 的 `NO(3,0)` 能挂，SPDT 的 `NO(3,-1)`/`NC(3,1)` 都不行。
  → 三端开关目前只能用两脚近似（`COM→信号`、`NO→地`，静止悬空＝高电平），
  这在本项目里是**已知有损替换**，不是笔误。donor 里已备 `kit_spdt.pdsprj`（含 `SW-SPDT`），
  等 writer 支持奇数偏移后可直接换。
- **引脚落在段中间不会连通**。器件符号把引线切断时（如 LED 的三角+横杠），
  引脚尖要取在**断点**上，不是符号的几何顶点。
- **`plan_route` 不避让器件本体**。器件摆得太挤时线可能压在图符上，改摆位。
- **密集扇出可能留下共线重叠**。实测编码器图（22 器件）在显示侧的扇出区
  有 2 处跨网共线重叠，善后整理也修不掉（替代走廊全被别的线占着）。
  **重叠不会连通**（Proteus 按端点判定，已实测），只是看着像连在一起。
  `plan_route` 会单独报这个数字，看到它就该知道"观感问题，不是电气问题"。
- **器件多到 20+ 时 A4 装不下**。编码器是 138×66 格，A4 只有 132×70。
  用 `verify.sheet.fit_to_content` 自动把图纸调到 156×84。
- **`verify-file` 是自证的**：它比"意图网表 ↔ 文件重建"，两边引脚名来自同一个 CDB，
  永远一致。它只能证明"画的和它声称的一致"，**不能证明画的和原图一致**。
  要验识别必须回原图对照。
- **`screenshot_check` 的比值跟视口有关**（同一张图不同缩放会给出 0.014 / 0.002）。
  它只能当"这个视口里有没有明显斜线"的提示，不是充分条件。
  **唯一权威的电气判据是 Proteus 编译出的 SDF。**
- **识别永远有不确定项**。图糊、位号缺失、结点看不清时就明说，让用户确认，
  不要编一个看起来合理的结果。


### 走不通的路（别重复试）

proteus844/experiments/ 里存着三条**负面结果**，跑起来永远 exit 0，只是数字留档：

| 脚本 | 想做什么 | 最好结果 |
|---|---|---|
| exp_fit.py | 把库符号吸附到图上引脚 | 半格内 23.8% |
| exp_pins_from_box.py | 只给器件框自动推引脚 | 8.8% |
| exp_place.py | 不拆电源网直接自动布局 | 编码器画不出来 |

原因都一样：**教材符号和库符号比例差 4 倍，跨库的几何匹配不成立**。
正确做法是 pin_hints 读编号 + check_against_image 复核 + uild_topology 布局。

## 7. GUI 兜底：写文件搞不定时，直接点 Proteus

实测可用的操作（都用 `proteus_*` 那组工具）：

| 操作 | 怎么做 | 验证 |
|---|---|---|
| 放器件 | `proteus_place(device, col, row, rotate=N)` | 9/9 成功 |
| **连导线** | 点第一个引脚 → 点第二个引脚 → 按 **`w`**（工具.自动连线） | SDF 确认成网 |
| **改属性** | `proteus_menu("编辑.查找并编辑元件")` → 输入位号 → 回车 → 点字段 → Ctrl+A → 输入 → 确定 | 阻值 10k→220 生效 |
| 存盘 / 编译网络表 | `proteus_save` / `proteus_netlist` | 可靠 |

### ⚠ 两个会让"按了没反应"的坑

**① 中文输入法会吃掉所有字母快捷键**
按 `w`、`-`、`F8` 之前先确认窗口的键盘布局。中文（0x0804）下 `w` 只是打开输入法候选框。
切换到 en-US 再按：

```powershell
$hkl = [KB]::LoadKeyboardLayout("00000409", 1)
[KB]::PostMessage($wnd, 0x0050, 0, $hkl)     # WM_INPUTLANGCHANGEREQUEST
```

**② 缩放会破坏坐标映射**
`F8`（查看整张图纸）之后网格校准会变成 `spacing=0`，此后 `col/row → 屏幕坐标` 全部失效。
遇到"点了没反应 / 点到滚动条上"，先 `proteus_calibrate` 重新校准，
并确认目标坐标落在画布矩形内（超出边界会点到滚动条）。

**③ 截图坐标是缩放过的**
`read_image` 看到的是预览图；对话框里点按钮要按**原始分辨率**换算，
否则会点在对话框外面（表现为"点了没反应"）。

**④ 放完器件要手动退出放置模式**
`proteus_place` 之后工具仍停在"放器件"状态，**后续任何画布点击都会再放一个同样的器件**。
实测就因此凭空多出一个 LED。可靠做法：放完立刻按 `Esc`(可能要多按几次)
或点左上角选择箭头，**并截图确认画面里没有品红色的器件残影**，再开始连线。

**⑤ `proteus_place_many` 会吞点**
一次放 3 个只落了 2 个（它自己会提示）。要稳就一个一个 `proteus_place`。

### 什么时候该用 GUI，什么时候不该

| 场景 | 建议 |
|---|---|
| 批量生成整张图 | **别用 GUI**。写文件 1 秒完成，GUI 要几百次点击且不可复现 |
| 补一根漏掉的线、改一个参数、挪一个器件 | **用 GUI**，快且合法 |
| 写文件被 Proteus 拒绝 | **用 GUI 兜底**，它画出来的格式一定对 |
| 最后肉眼确认 | 截图，别指望工具报错 |

**结论**：GUI 路现在能"点"，但状态很脆（模式、输入法、缩放、坐标换算四层坑）。
整图生成仍以写文件为准，GUI 只当补救手段。


**⑥ proteus_erc 的路径必须以 .SDF 结尾** —— 传别的后缀它按扩展名找文件，会报「网络表没有生成」。
