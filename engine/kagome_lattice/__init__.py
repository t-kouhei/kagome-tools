"""カゴメ格子解析ツール（先生の資料準拠・第1段階）。

先生のカゴメ格子モデルを、論理の保証を崩さずに解析ツールとして形にする。
変数の意味付け（どの物理量を当てはめるか）は使う側が分野ごとに決める。
"""
from .model import KagomeModel, EdgeValues, TURN_TABLE  # noqa: F401

__version__ = "1.0.3"
