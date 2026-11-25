"""共通の数理パラメータと、特許版・交通版での意味付け。

版は計算式を変更しない。単位の変換も行わない。
並列経路数 m は等価な経路をまとめた数。格子の接続本数とは別。
"""
from copy import deepcopy

PROFILE_NAMES = {"patent": "特許版（基本解析）", "traffic": "交通版"}

PARAMETERS = {
    "m": {"label": "並列経路数", "unit": "本（等価本数も可）",
          "meaning": "各素辺にまとめた並列経路の数。共通計算では正の実数の重みとして扱う。"},
    "L": {"label": "素辺長", "unit": "選択した長さ単位",
          "meaning": "各素辺の長さ。格子図の描画上の長さとは独立した入力。"},
    "v": {"label": "輸送速度", "unit": "長さ/時間",
          "meaning": "素辺上の輸送速度。Lと共通の長さ単位を使う。"},
    "V": {"label": "輸送流量", "unit": "輸送量/時間",
          "meaning": "各素辺の単位時間あたりの輸送量。観測入力または入口からの伝播で求める。"},
    "T": {"label": "分布の幅", "unit": "規格化量εと同じ",
          "meaning": "フェルミ・ディラック型分布の幅を定める正のパラメータ。物理温度との対応は用途ごとに定める。"},
    "mu": {"label": "臨界基準", "unit": "規格化量εと同じ",
           "meaning": "分布が1/2になる規格化量。θ=1/2のときの臨界値。"},
}

TRAFFIC_PARAMETERS = {
    "m": {"label": "車線数", "unit": "車線（等価車線数も可）"},
    "L": {"label": "道路長", "unit": "km"},
    "v": {"label": "走行速度", "unit": "km/h"},
    "V": {"label": "交通流量", "unit": "台/h"},
}


def profile_info(profile, norm="m"):
    if profile not in PROFILE_NAMES:
        raise ValueError(f"不明な版: {profile}（patent / traffic を指定する）")
    parameters = deepcopy(PARAMETERS)
    if profile == "traffic":
        for key, details in TRAFFIC_PARAMETERS.items():
            parameters[key].update(details)
        unit = {"k": "台/km/車線", "m": "台/h/車線", "mvl": "台/h²/車線"}[norm]
        for key in ("T", "mu"):
            parameters[key]["unit"] = unit
    return {"id": profile, "name": PROFILE_NAMES[profile], "parameters": parameters,
            "normalization": {"k": "J=V/(v·m)", "m": "J=V/m", "mvl": "J=V·v/(L·m)"}[norm],
            "note": "m・L・v・V・T・μと分岐割合は両版に共通。Vは単位時間あたりの総流量。原資料のnからはV=n·v/Lで換算する。"
                    "新規の基本設定はj=V/m、τ=j_in·β·L_in/(m_out·L_out)。"
                    "版の選択による値・単位の自動変換は行わない。"
                    "規格化・回転量の式と先生の理論との対応には確認事項が残る。"}


def presentation_text(text, profile):
    """共有の画面・説明文を特許版の用語にする。数値・識別子には触れない。"""
    if profile == "traffic":
        return text
    for source, target in (
        ("道路インフラ限界", "方向別の標準総量"),
        ("渋滞臨界状態", "臨界状態"),
        ("1 車線あたりの密度", "並列経路あたりの輸送密度"),
        ("交通量", "輸送流量"), ("交通密度", "輸送密度"),
        ("台数から", "輸送量から"), ("交差点", "節点"),
        ("車線数", "並列経路数"), ("道路", "経路"),
    ):
        text = text.replace(source, target)
    return text
