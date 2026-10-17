"""Static literal/template callback routing audit. Dynamic prefixes are reported as gaps."""
import ast
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]


def value(node, data):
    if isinstance(node, ast.Constant): return node.value
    if isinstance(node, (ast.Set, ast.List, ast.Tuple)): return [value(n,data) for n in node.elts]
    if isinstance(node, ast.Attribute) and node.attr=='data': return data
    if isinstance(node, ast.Compare) and len(node.ops)==1:
        left,right=value(node.left,data),value(node.comparators[0],data)
        if isinstance(node.ops[0],ast.Eq): return left==right
        if isinstance(node.ops[0],ast.NotEq): return left!=right
    if isinstance(node,ast.BinOp):
        if isinstance(node.op,ast.BitOr): return value(node.left,data) or value(node.right,data)
        if isinstance(node.op,ast.BitAnd): return value(node.left,data) and value(node.right,data)
    if isinstance(node,ast.UnaryOp) and isinstance(node.op,ast.Invert): return not value(node.operand,data)
    if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute):
        target=value(node.func.value,data); args=[value(n,data) for n in node.args]
        if node.func.attr=='startswith': return target.startswith(*args)
        if node.func.attr=='endswith': return target.endswith(*args)
        if node.func.attr=='in_': return target in args[0]
        if node.func.attr=='regexp': return bool(re.search(args[0],target))
    raise ValueError(ast.unparse(node))


handlers=[]; buttons=[]; gaps=[]
for path in [ROOT/'telegram_bot.py', *sorted((ROOT/'handlers').glob('*.py'))]:
    tree=ast.parse(path.read_text()); filename=str(path.relative_to(ROOT))
    for node in ast.walk(tree):
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                if isinstance(dec,ast.Call) and isinstance(dec.func,ast.Attribute) and dec.func.attr=='callback_query':
                    handlers.append((filename,node.name,dec.args))
        if isinstance(node,ast.keyword) and node.arg=='callback_data':
            if isinstance(node.value,ast.Constant) and isinstance(node.value.value,str):
                buttons.append((filename,node.value.lineno,node.value.value,'literal'))
            elif isinstance(node.value,ast.JoinedStr) and node.value.values and isinstance(node.value.values[0],ast.Constant):
                sample=''.join(n.value if isinstance(n,ast.Constant) else '1' for n in node.value.values)
                buttons.append((filename,node.value.lineno,sample,'template'))
            else:
                gaps.append({'file':filename,'expression':ast.unparse(node.value)})

unmatched=[]; unsupported=set(); overlong=[]
for filename,line,sample,kind in buttons:
    matched=[]
    for hfile,name,args in handlers:
        if not args: continue
        try:
            if all(value(arg,sample) for arg in args): matched.append(name)
        except (ValueError,TypeError) as exc: unsupported.add(str(exc))
    if not matched: unmatched.append({'file':filename,'line':line,'sample':sample,'kind':kind})
    if len(sample.encode())>64: overlong.append({'file':filename,'line':line,'bytes':len(sample.encode())})
result={'handlers':len(handlers),'checked_buttons':len(buttons),'dynamic_gaps':len(gaps),'unsupported_filters':sorted(unsupported),'unmatched':unmatched,'overlong_samples':overlong}
(ROOT/'audit_checks/callback_map.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps(result,ensure_ascii=False,indent=2))
