# 贡献与开发说明

## 跑起来

```bash
python -m pip install -r requirements.txt
python -m proteus844.selftest        # 10 项，约 12 秒
```

自检不依赖 Proteus —— 它只跑命令行级、文件级、回归级的检查。
涉及 Proteus 引擎的验收（编译 SDF）需要本机装了 Proteus 8.15。

## 目录约定

- `proteus844/` 是包本体，可 `import proteus844`
- `tests/` 里的测试都应能在**没有 Proteus、没有示例图**的环境下通过或跳过
- `experiments/` 放走不通的路，跑起来永远 exit 0，只是把数字留档
- 改 `vendor/ref844/` 必须在 [NOTICE](NOTICE) 里记一笔

## 提交前

```bash
python -m proteus844.selftest          # 必须 10/10
python -m proteus844.tests.regression  # 必须 13/13
```

## 不要提交

- `*.pdsprj` / `*.SDF` 的**生成产物**（`donors/` 里的模板要提交，那是必需品）
- Proteus 打开工程时生成的 `Project Backups/`、`*.ASV`、`*.workspace`
- 任何教材扫描图（版权）
