"""Regenerate synthetic inputs for the existing direction admission operation."""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'engine'))
from kagome_lattice.tutorial import tutorial_state


def create():
    folder = ROOT / 'examples/admission'
    folder.mkdir(parents=True, exist_ok=True)
    for name, demand, closed in [('low', 1000, None), ('high', 6000, None),
                                 ('direction-6-off', 6000, 6)]:
        state = tutorial_state('patent')
        state.update(name={'low': '入口調整：全量を受け入れる', 'high': '入口調整：要求量の3分の1を受け入れる',
                           'direction-6-off': '入口調整：向き6の外部流入を0にする'}[name],
                     mode='propagate', global_rule='direction', local_rule='none')
        for row in state['tables']['branching']:
            row.update(S='1', R='0', L='0')
        for row in state['tables']['entrances']:
            row['inflow'] = str(0 if row['in_road'] == closed else demand)
        (folder / (name + '.json')).write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n',
                                              encoding='utf-8', newline='\n')
    print('Wrote 3 synthetic direction admission inputs.')


if __name__ == '__main__':
    create()
