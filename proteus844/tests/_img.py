"""测试用的源图查找。

公开仓库里**不包含**这张教材扫描图（版权原因）。没有就跳过相关测试，
而不是报失败 —— 那些测试验证的是几何算法，与具体那张图无关。
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def source_image():
    """返回源图路径；没有就返回 None（调用方应跳过）。"""
    p = os.path.join(HERE, "encoder_source.png")
    return p if os.path.exists(p) else None


def need_image(test_name):
    p = source_image()
    if p is None:
        print(f"⏭  {test_name} 跳过：仓库不含 source image（版权原因）")
        print("   要跑这个测试，把一张编码器电路图放到 tests/encoder_source.png")
        return None
    return p
