"""Strict validator for the deliberately small event-schema vocabulary; no dependencies."""
import re
from board_workflow import timestamp

KEYWORDS = {'$schema','$id','title','description','type','enum','const','required','properties','additionalProperties','items','minItems','maxItems','uniqueItems','minLength','maxLength','pattern','format','allOf','anyOf','not','if','then','else'}

def check_schema(schema):
    unknown = set(schema) - KEYWORDS
    if unknown: raise ValueError(f'unsupported schema keywords: {sorted(unknown)}')
    for key in ('items','not','if','then','else'):
        if key in schema: check_schema(schema[key])
    for value in schema.get('properties',{}).values(): check_schema(value)
    for key in ('allOf','anyOf'):
        for value in schema.get(key,[]): check_schema(value)

def errors(value, schema, at='$'):
    out=[]
    def bad(msg): out.append(f'{at}: {msg}')
    types={'object':lambda x:isinstance(x,dict), 'array':lambda x:isinstance(x,list),
           'string':lambda x:isinstance(x,str), 'null':lambda x:x is None,
           'integer':lambda x:type(x) is int, 'number':lambda x:type(x) in (int,float), 'boolean':lambda x:type(x) is bool}
    if 'type' in schema:
        ts=schema['type']; ts=ts if isinstance(ts,list) else [ts]
        if not any(types[t](value) for t in ts): return [f'{at}: expected {ts}']
    if 'const' in schema and value != schema['const']: bad('wrong constant')
    if 'enum' in schema and value not in schema['enum']: bad('not an allowed value')
    if isinstance(value,dict):
        for key in schema.get('required',[]):
            if key not in value: bad(f'missing {key}')
        props=schema.get('properties',{})
        for key, item in value.items():
            if key in props: out += errors(item,props[key],at+'.'+key)
            elif schema.get('additionalProperties') is False: bad(f'unknown field {key}')
    if isinstance(value,str):
        if len(value)<schema.get('minLength',0): bad('too short')
        if len(value)>schema.get('maxLength',float('inf')): bad('too long')
        if 'pattern' in schema and not re.search(schema['pattern'],value): bad('pattern mismatch')
        if schema.get('format') == 'date-time':
            try: timestamp(value)
            except (ValueError,TypeError): bad('invalid timestamp/timezone')
    if isinstance(value,list):
        if len(value)<schema.get('minItems',0): bad('too few items')
        if len(value)>schema.get('maxItems',float('inf')): bad('too many items')
        if schema.get('uniqueItems') and any(x in value[:i] for i,x in enumerate(value)): bad('duplicate items')
        if 'items' in schema:
            for i,item in enumerate(value): out += errors(item,schema['items'],at+f'[{i}]')
    for branch in schema.get('allOf',[]): out += errors(value,branch,at)
    if 'anyOf' in schema and not any(not errors(value,b,at) for b in schema['anyOf']): bad('no alternative matched')
    if 'not' in schema and not errors(value,schema['not'],at): bad('forbidden combination')
    if 'if' in schema:
        branch='then' if not errors(value,schema['if'],at) else 'else'
        if branch in schema: out += errors(value,schema[branch],at)
    return out


def history_errors(value, schema, *, committed):
    """Read compatibility only; new posts must continue to use errors().

    Early v1 writers admitted long ordinary summaries. Preserve committed
    history up to the existing details budget, with a visible warning. No
    routing, identity, privacy, v2, or other schema errors are relaxed.
    """
    problems = errors(value, schema)
    if (committed and value.get('schema_version') == 1
            and value.get('source_policy') == 'ordinary'
            and isinstance(value.get('summary'), str)
            and len(value['summary']) <= 4000
            and problems == ['$.summary: too long']):
        return [], [f"legacy v1 summary ({len(value['summary'])} characters): "
                    "read unchanged; new posts remain limited to 1000"]
    return problems, []
