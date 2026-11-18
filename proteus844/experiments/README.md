# 负面实验记录（Negative results）

这里放的是**试过但走不通**的路子。它们不是测试，**不参与回归**，跑起来永远 `exit 0`。
保留的价值：以后再想"要不要试个更聪明的办法"时，先看这里的数字。

| 脚本 | 想做什么 | 最好结果 | 为什么不行 |
|---|---|---|---|
| `exp_fit.py` | 把库里的符号"吸附"到图上的引脚 | 半格内 23.8% | 教材符号和库符号比例差 **4 倍**（隐含 ppg 2.20~8.75），形状本身就不同 |
| `exp_pins_from_box.py` | 只给器件框，自动推各引脚位置 | 8.8% | 同一张图上符号画法不统一：有的画了引脚桩，有的导线直接顶到本体 |
| `exp_place.py` | 用原始网表直接自动布局 | 编码器布局 120×224 | 电源网没拆成端子，十几脚的星形结点画不出来（`test_topology` 已覆盖正确做法） |

三条都指向同一个结论：

> **跨库的感知问题（定符号、定引脚）没法靠几何算法解决。**
> 能做的是"减轻"和"校验"——`pin_hints` 让 AI 读编号、`check_against_image` 挑可疑，
> 而不是假装能全自动。

跑法：

```bash
python -m proteus844.experiments.exp_fit
python -m proteus844.experiments.exp_pins_from_box
python -m proteus844.experiments.exp_place
```
