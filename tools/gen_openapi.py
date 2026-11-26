# -*- coding: utf-8 -*-
"""从 Spring MVC 源码注解反向生成 OpenAPI 3.0 文档。

适用场景：被测系统未集成 Swagger/springdoc，无法从运行服务获取 /v3/api-docs，
但 Controller 用了标准 @RestController / @RequestMapping / @Get/PostMapping 注解。
本工具静态解析源码，输出可被 Swagger UI / OpenAPI 工具直接消费的标准 JSON。

用法：
    python tools/gen_openapi.py \
        --src D:/shopping/backend/src/main/java \
        --out projects/shopping/data/openapi.json \
        --base-url http://127.0.0.1:8080 \
        --title "Shopping API"

说明：这是「源码反向生成」，不是运行时 Swagger。请求/响应 body 只到结构层级
（Result 信封 + Java 类型映射），字段级 schema 仍需按真实响应补全——框架的
contracts.yaml 才是字段级契约的权威来源。
"""
import argparse
import json
import re
from pathlib import Path

METHOD_MAP = {
    'GetMapping': 'get', 'PostMapping': 'post', 'PutMapping': 'put',
    'DeleteMapping': 'delete', 'PatchMapping': 'patch',
}
TYPE_MAP = {
    'Long': {'type': 'integer', 'format': 'int64'},
    'Integer': {'type': 'integer', 'format': 'int32'},
    'int': {'type': 'integer', 'format': 'int32'},
    'String': {'type': 'string'},
    'Boolean': {'type': 'boolean'},
    'boolean': {'type': 'boolean'},
    'Double': {'type': 'number', 'format': 'double'},
}


def unwrap(text):
    """Result<T> -> T。"""
    text = text.strip()
    m = re.match(r'Result\s*<\s*(.+)\s*>$', text)
    return m.group(1).strip() if m else text


def schema_for(java_type):
    t = java_type.strip()
    if t in TYPE_MAP:
        return dict(TYPE_MAP[t])
    m = re.match(r'List\s*<\s*(.+)\s*>$', t)
    if m:
        return {'type': 'array', 'items': schema_for(m.group(1))}
    m = re.match(r'Map\s*<[^,]+,\s*(.+)\s*>$', t)
    if m:
        return {'type': 'object', 'additionalProperties': schema_for(m.group(1))}
    if t.endswith('?') or t == 'void':
        return {}
    return {'$ref': '#/components/schemas/%s' % t}


def class_doc(lines, line_no):
    """取方法上方的 Javadoc 摘要，支持单行与多行块。"""
    i = line_no - 1
    if i < 0:
        return ''
    one_line = re.match(r'\s*/\*\*\s*(.+?)\s*\*/\s*$', lines[i])
    if one_line:
        return one_line.group(1)
    while i >= 0 and not lines[i].strip().endswith('*/'):
        # 遇到方法签名/右花括号说明这注释属于别的成员，不跨过去
        if re.match(r'\s*(public|private|protected)\s', lines[i]) or lines[i].strip() == '}':
            return ''
        i -= 1
    if i < 0:
        return ''
    buf = []
    j = i - 1
    while j >= 0 and '/**' not in lines[j]:
        raw = lines[j].strip()
        if not raw.startswith(('*', 'import ', 'package ', 'public ', '@')):
            break
        buf.append(raw.lstrip('*').strip())
        j -= 1
    for item in reversed(buf):
        if item and not item.startswith('@'):
            return item
    return ''


def extract_params(params_raw):
    """按括号深度切分参数，逐个解析注解。"""
    parts, depth, start = [], 0, 0
    for i, ch in enumerate(params_raw):
        if ch in '(<':
            depth += 1
        elif ch in ')>`':
            depth -= 1
        elif ch == ',' and depth == 0:
            parts.append(params_raw[start:i].strip())
            start = i + 1
    if params_raw[start:].strip():
        parts.append(params_raw[start:].strip())

    params, request_body = [], False
    for part in parts:
        if re.match(r'@RequestBody\s+', part):
            request_body = True
            continue
        m = re.match(r'@(RequestParam|PathVariable|RequestHeader)\s*\(([^)]*)\)\s*(.+)$', part)
        if not m:
            continue  # HttpServletRequest / HttpServletResponse 等容器参数
        kind, attrs, rest = m.group(1), m.group(2), m.group(3).strip()
        name_match = re.search(r'["\']([^"\']+)["\']', attrs)
        tm = re.match(r'([\w<>?,.\s\[\]]+?)\s+(\w+)$', rest)
        if not tm:
            continue
        jtype, pname = tm.group(1).strip(), tm.group(2)
        dm = re.search(r'defaultValue\s*=\s*["\']([^"\']*)["\']', attrs)
        optional = bool(re.search(r'required\s*=\s*false', attrs))
        params.append({
            'name': name_match.group(1) if name_match else pname,
            'in': 'path' if kind == 'PathVariable' else ('header' if kind == 'RequestHeader' else 'query'),
            'required': (kind == 'PathVariable') or not optional,
            'schema': schema_for(jtype),
            **({'example': dm.group(1)} if dm else {}),
        })
    return params, request_body


def parse_controller(path):
    text = path.read_text(encoding='utf-8')
    lines = text.splitlines()
    class_path = ''
    m = re.search(r'@RequestMapping\s*\(\s*["\']([^"\']+)["\']\s*\)', text)
    if m:
        class_path = m.group(1).rstrip('/')

    endpoints = []
    pattern = re.compile(
        r'@(GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping)'
        r'(?:\s*\(\s*(?:value\s*=\s*)?["\']([^"\']*)["\']\s*\))?'
    )
    for m in pattern.finditer(text):
        anno, sub = m.group(1), m.group(2) or ''
        line_no = text[:m.start()].count('\n')
        tail = text[m.end():m.end() + 1200]

        open_i = tail.find('(')
        if open_i < 0:
            continue
        head = tail[:open_i]
        sig = re.search(r'public\s+([\w<>?,.\s\[\]]+?)\s+(\w+)\s*$', head)
        if not sig:
            continue
        ret, name = sig.group(1).strip(), sig.group(2)
        depth, close_i = 0, -1
        for i in range(open_i, len(tail)):
            if tail[i] == '(':
                depth += 1
            elif tail[i] == ')':
                depth -= 1
                if depth == 0:
                    close_i = i
                    break
        if close_i < 0:
            continue

        full_path = (class_path + '/' + sub.lstrip('/')).rstrip('/') or '/'
        if not full_path.startswith('/'):
            full_path = '/' + full_path
        params, request_body = extract_params(tail[open_i + 1:close_i])

        endpoints.append({
            'method': METHOD_MAP[anno],
            'path': full_path,
            'operationId': '%s_%s_%d' % (METHOD_MAP[anno], name, len(endpoints) + 1),
            'summary': class_doc(lines, line_no),
            'tags': [path.stem.replace('Controller', '')],
            'parameters': params,
            'requestBody': ({'required': True, 'content': {'application/json': {'schema': {'type': 'object'}}}}
                            if request_body else None),
            'responses': {
                '200': {
                    'description': '业务信封 Result（code/message/data）',
                    'content': {'application/json': {'schema': {
                        'type': 'object',
                        'properties': {
                            'code': {'type': 'integer'},
                            'message': {'type': 'string'},
                            'data': schema_for(unwrap(ret)),
                        },
                    }}},
                },
            },
        })
    return endpoints


def main():
    ap = argparse.ArgumentParser(description='从 Spring MVC 注解反向生成 OpenAPI 3.0')
    ap.add_argument('--src', required=True, help='Java 源码根目录（递归找 *Controller*.java）')
    ap.add_argument('--out', required=True, help='输出 JSON 路径')
    ap.add_argument('--base-url', default='http://127.0.0.1:8080', help='servers[0].url')
    ap.add_argument('--title', default='API（源码反向生成）', help='info.title')
    args = ap.parse_args()

    src, out = Path(args.src), Path(args.out)
    if not src.is_dir():
        raise SystemExit('源码目录不存在：%s' % src)

    endpoints = []
    for java in sorted(src.rglob('*Controller*.java')):
        endpoints.extend(parse_controller(java))

    paths = {}
    for ep in endpoints:
        op = {k: v for k, v in ep.items() if k not in ('method', 'path') and v is not None}
        paths.setdefault(ep['path'], {})[ep['method']] = op

    doc = {
        'openapi': '3.0.3',
        'info': {
            'title': args.title,
            'version': '1.0.0',
            'description': '被测系统未集成 Swagger，本文档由源码 @RestController 注解静态解析生成，'
                           '供接口自动化接入参考。字段级契约以项目 contracts.yaml 为准。',
        },
        'servers': [{'url': args.base_url}],
        'paths': paths,
        'components': {'schemas': {}},
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding='utf-8')
    print('生成 OpenAPI: %s' % out)
    print('paths=%d, operations=%d' % (len(paths), len(endpoints)))


if __name__ == '__main__':
    main()
