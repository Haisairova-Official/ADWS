"""Small conservative include reader shared by installer audits.

This is not a general KDL parser. Unknown syntax must be reported for review,
while standard optional includes may be absent without creating a conflict.
"""
import json
import re


def include(line):
    stripped=line.strip()
    match=re.match(r'^include\s+',stripped)
    if not match:return None
    tail=stripped[match.end():];tokens=[];index=0
    while index<len(tail):
        if tail[index].isspace():index+=1;continue
        if tail.startswith('//',index):break
        if tail[index]==';':
            rest=tail[index+1:].strip()
            if rest and not rest.startswith('//'):raise ValueError('Multiple KDL statements need review')
            break
        match=re.match(r'"(?:[^"\\]|\\.)*"|[^\s;]+',tail[index:])
        if not match:raise ValueError('Unparsed include token')
        tokens.append(match[0]);index+=len(match[0])
    paths=[];optional=False;attributes=[]
    for token in tokens:
        if token.startswith('"'):
            try:value=json.loads(token)
            except (ValueError,TypeError) as error:raise ValueError('Unparsed include path') from error
            if not isinstance(value,str) or not value or '\0' in value:raise ValueError('Invalid include path')
            paths.append(value)
        elif token in ('optional=true','optional=false'):
            attributes.append(token);optional=token=='optional=true'
        else:raise ValueError('Unknown include attribute')
    if len(paths)!=1 or len(attributes)>1:raise ValueError('Include needs one path and at most one optional attribute')
    return paths[0],optional


def spawn(line):
    """Read one literal startup node; never infer argv from complex KDL."""
    match=re.match(r'^\s*(spawn-at-startup|spawn-sh-at-startup)\s+',line)
    if not match:raise ValueError('Not a startup node')
    name=match[1];tail=line[match.end():];args=[];decoder=json.JSONDecoder()
    while tail:
        tail=tail.lstrip()
        if not tail or tail.startswith('//'):break
        if tail.startswith(';'):
            rest=tail[1:].strip()
            if rest and not rest.startswith('//'):raise ValueError('Multiple startup nodes need review')
            break
        if not tail.startswith('"'):raise ValueError('Startup arguments must be literal strings')
        try:value,end=decoder.raw_decode(tail)
        except ValueError as error:raise ValueError('Unparsed startup string') from error
        if not isinstance(value,str) or '\0' in value:raise ValueError('Invalid startup argument')
        args.append(value);tail=tail[end:]
        if tail and not tail[0].isspace() and not tail.startswith((';','//')):raise ValueError('Unparsed startup separator')
    if not args or (name=='spawn-sh-at-startup' and len(args)!=1):raise ValueError('Invalid startup argument count')
    return name,args
