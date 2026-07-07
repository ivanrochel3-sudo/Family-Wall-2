import ast
import difflib
import subprocess
from pathlib import Path

root = Path(r'c:/Users/ivanr/OneDrive/Desktop/Git Test/Family-Wall-2')
current_text = (root / 'FamilyWall.py.py').read_text(encoding='utf-8')
old_text = subprocess.check_output(['git', 'show', 'HEAD:FamilyWall.py.py'], cwd=str(root), text=True)


def extract(source: str, name: str):
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(source, node)
    raise RuntimeError(name)

out = []
for name in ['make_sequence_xml_body', 'make_photo_clipitem', 'make_border_clipitem']:
    old = extract(old_text, name)
    new = extract(current_text, name)
    out.append(f'--- {name} (old)')
    out.append(f'+++ {name} (new)')
    out.extend(
        difflib.unified_diff(
            old.splitlines(),
            new.splitlines(),
            fromfile=f'{name} (old)',
            tofile=f'{name} (new)',
            lineterm='',
        )
    )
    out.append('')

(root / 'tmp_diff_output.txt').write_text('\n'.join(out), encoding='utf-8')
