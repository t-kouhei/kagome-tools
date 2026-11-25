"""意図を説明できる代表ケース。実測データではない。"""
from .tutorial import tutorial_state

CATALOG = [
    {'id':'uniform', 'name':'一様な流れ', 'description':'全素辺の本数・長さ・速度・流量をそろえた手計算用の例。',
     'check':'j=800、六角形の右回り600・左回り360・正味240を確認します。'},
    {'id':'bottleneck', 'name':'一部の経路だけ細い', 'description':'各入口に6000を与え、C(2,2)-1だけ並列経路数を4から1にします。全入口の合計は6000×入口数です。',
     'check':'全体の方向別集計と、1本の素辺の容量超過を区別します。調整前の例で、自動的に迂回しません。'},
    {'id':'right_bias', 'name':'右回りが多い', 'description':'右回りの割合0.35、左回り0.05、直進0.60。Vと本数は一様な例と同じです。',
     'check':'六角形の右回り840・左回り120・正味720。標準も同じ分岐割合で再計算されます。'},
    {'id':'unequal_length', 'name':'長さが不均一', 'description':'C(2,2)-1の長さだけ0.5から1.0にし、観測流量Vは1600に固定します。',
     'check':'jは変わらず、入辺・出辺の長さ比を使うτが変化します。素片内の量nを固定する例ではありません。'},
]


def example_state(identifier, profile):
    description = next((item for item in CATALOG if item['id']==identifier), None)
    if description is None:
        raise ValueError('代表ケースが不明です')
    state = tutorial_state(profile)
    state['name'] = description['name']
    chosen = next(row for row in state['tables']['edges'] if (row['node_type'],row['i'],row['j'],row['road']) == ('C',2,2,1))
    if identifier == 'bottleneck':
        state['mode'] = 'propagate'
        for row in state['tables']['edges']:
            row.update(m='4', mu='5000', T='500', V='')
        chosen['m'] = '1'
        for row in state['tables']['entrances']:
            row['inflow'] = '6000'
    elif identifier == 'right_bias':
        for row in state['tables']['branching']:
            row.update(S='0.6', R='0.35', L='0.05')
    elif identifier == 'unequal_length':
        chosen['L'] = '1.0'
    state['example'] = {'id':identifier, **description, 'synthetic':True}
    return state
