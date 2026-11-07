#!/usr/bin/env python3
"""Adapt a decompiled stock evert DTS to the phase-0 4.19 bindings.

Usage: patch_evert_rpm.py STOCK.dts PATCHED.dts
Only plain, decompiled DTS is supported.
"""
import argparse
from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import tempfile

TOKENS = re.compile(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|[{};]', re.S)
HEADER = re.compile(r'\s*(?:(\w+)\s*:\s*)?(/|[\w,.@+?#-]+)\s*')
PROPERTY = re.compile(r'\s*([\w,#.+?@-]+)\s*(?:=\s*(.*?))?\s*;', re.S)


@dataclass
class Node:
    path: str
    start: int
    opening: int
    label: str = ""
    closing: int = -1
    end: int = -1
    children: list = field(default_factory=list)


def without_comments(text):
    return TOKENS.sub(
        lambda m: re.sub(r'[^\n]', ' ', m[0])
        if m[0].startswith(('/*', '//')) else m[0], text)


def parse_nodes(text):
    nodes, stack, labels = {}, [], set()
    boundary = 0
    closed_at = None
    for match in TOKENS.finditer(text):
        token = match[0]
        if token.startswith(('/*', '//')):
            continue
        if closed_at is not None:
            if token != ';' or without_comments(
                    text[closed_at:match.start()]).strip():
                raise ValueError('missing semicolon after node')
            closed_at = None
            boundary = match.end()
            continue
        if token.startswith('"'):
            continue
        if token == '{':
            header = HEADER.fullmatch(
                without_comments(text[boundary:match.start()]))
            if not header:
                raise ValueError('unsupported or malformed node header')
            label, name = header.groups()
            if not stack:
                if name != '/' or nodes:
                    raise ValueError('expected exactly one root node')
                path = '/'
            else:
                if name == '/':
                    raise ValueError('nested root node')
                path = stack[-1].path.rstrip('/') + '/' + name
            if path in nodes or label and label in labels:
                raise ValueError('duplicate node path or label: ' + path)
            node = Node(path, boundary, match.start(), label or '')
            nodes[path] = node
            if label:
                labels.add(label)
            if stack:
                stack[-1].children.append(node)
            stack.append(node)
        elif token == '}':
            if not stack:
                raise ValueError('unmatched closing brace')
            node = stack.pop()
            node.closing, node.end = match.start(), match.end()
            closed_at = match.end()
        elif token == ';' and not stack:
            directive = without_comments(
                text[boundary:match.start()]).strip()
            if nodes or not (
                    directive == '/dts-v1/' or re.fullmatch(
                        r'/memreserve/\s+(?:0x[0-9a-fA-F]+|[0-9]+)\s+'
                        r'(?:0x[0-9a-fA-F]+|[0-9]+)', directive)):
                raise ValueError('unsupported top-level statement')
        boundary = match.end()
    if stack or '/' not in nodes or closed_at is not None:
        raise ValueError('missing root, unclosed node or missing semicolon')
    if without_comments(text[boundary:]).strip():
        raise ValueError('unexpected text after root')
    for node in nodes.values():
        properties(text, node)
    return nodes, labels


def properties(text, node):
    """Return direct properties and their original source spans."""
    spans, cursor = [], node.opening + 1
    for child in node.children:
        spans.append((cursor, child.start))
        cursor = child.end
    spans.append((cursor, node.closing))
    result = {}
    for begin, end in spans:
        segment = text[begin:end]
        start = 0
        for token in TOKENS.finditer(segment):
            if token[0] != ';':
                continue
            statement = without_comments(segment[start:token.end()])
            if statement.strip() != ';':
                prop = PROPERTY.fullmatch(statement)
                if not prop:
                    raise ValueError('unsupported property in ' + node.path)
                name, value = prop.groups()
                if name in result:
                    raise ValueError(
                        'duplicate property: ' + node.path + '/' + name)
                result[name] = (
                    value, begin + start + prop.start(1),
                    begin + token.end())
            start = token.end()
        if without_comments(segment[start:]).strip():
            raise ValueError('unterminated property in ' + node.path)
    return result


def cells(value):
    pattern = r'\s*<\s*(?:(?:0x[0-9a-fA-F]+|[0-9]+)\s*)*>\s*'
    if value is None or not re.fullmatch(pattern, value):
        raise ValueError('expected literal integer cells')
    return [
        int(v, 16) if v.lower().startswith('0x') else int(v, 10)
        for v in re.findall(r'0x[0-9a-fA-F]+|[0-9]+', value)
    ]


PROVIDERS = '''

        apcs_glb: mailbox@17911000 {
            compatible = "qcom,sdm660-apcs-hmss-global";
            reg = <0x17911000 0x1000>;
            #mbox-cells = <1>;
        };

        rpm_msg_ram: rpm-msg-ram@778000 {
            compatible = "qcom,rpm-msg-ram";
            reg = <0x778000 0x7000>;
        };

        rpm-glink {
            compatible = "qcom,glink-rpm";
            interrupts = <0 0xa8 1>;
            qcom,rpm-msg-ram = <&rpm_msg_ram>;
            mboxes = <&apcs_glb 0>;
        };

        tcsr_mutex_block: syscon@1f40000 {
            compatible = "syscon";
            reg = <0x1f40000 0x20000>;
        };

        tcsr_mutex: hwlock {
            compatible = "qcom,tcsr-mutex";
            syscon = <&tcsr_mutex_block 0 0x1000>;
            #hwlock-cells = <1>;
        };
'''

SMEM_RESERVATION = '''

        smem_mem: smem-mem@86000000 {
            compatible = "removed-dma-pool";
            no-map;
            reg = <0 0x86000000 0 0x200000>;
        };
'''


def patch(text):
    nodes, labels = parse_nodes(text)
    changes = []

    def require_node(path):
        if path not in nodes:
            raise ValueError('required node not found: ' + path)
        return nodes[path]

    def props(path):
        return properties(text, require_node(path))

    def require_value(items, key, expected):
        if key not in items or items[key][0] != expected:
            raise ValueError('unexpected or missing ' + key)

    def require_cells(items, key, expected):
        if key not in items or cells(items[key][0]) != expected:
            raise ValueError('unexpected or missing cells: ' + key)

    def set_property(node, items, key, value):
        replacement = key + ' = ' + value + ';'
        if key in items:
            changes.append((items[key][1], items[key][2], replacement))
        else:
            position = (
                node.children[0].start if node.children else node.closing)
            changes.append((
                position, position, '\n        ' + replacement + '\n'))

    root = props('/')
    require_value(root, 'model', '"Evert"')
    compatible = root.get('compatible', (None,))[0]
    strings = (
        re.findall(r'"(?:\\.|[^"\\])*"', compatible)
        if compatible is not None else []
    )
    if '"qcom,sdm630-evert"' not in strings:
        raise ValueError('input is not an evert SDM630 tree')

    soc = require_node('/soc')
    reserved = require_node('/reserved-memory')
    for node, expected in ((soc, [1]), (reserved, [2])):
        items = properties(text, node)
        require_cells(items, '#address-cells', expected)
        require_cells(items, '#size-cells', expected)

    added_paths = (
        '/soc/mailbox@17911000', '/soc/rpm-msg-ram@778000',
        '/soc/rpm-glink', '/soc/syscon@1f40000', '/soc/hwlock',
        '/reserved-memory/smem-mem@86000000',
    )
    added_labels = {
        'apcs_glb', 'rpm_msg_ram', 'tcsr_mutex_block',
        'tcsr_mutex', 'smem_mem',
    }
    if any(path in nodes for path in added_paths) or labels & added_labels:
        raise ValueError(
            'input is already/partially patched or has provider collisions')

    native = require_node('/soc/qcom,glink-smem-native-xprt-rpm@778000')
    items = properties(text, native)
    require_value(items, 'compatible', '"qcom,glink-rpm-native-xprt"')
    set_property(native, items, 'status', '"disabled"')

    rpm = require_node('/soc/qcom,rpm-smd')
    items = properties(text, rpm)
    require_value(items, 'compatible', '"qcom,rpm-glink"')
    require_value(items, 'qcom,glink-edge', '"rpm"')
    require_value(items, 'rpm-channel-name', '"rpm_requests"')
    if 'interrupts' in items:
        require_cells(items, 'interrupts', [0, 0xa8, 1])
    if 'rpm-channel-type' in items:
        require_cells(items, 'rpm-channel-type', [0xf])
    set_property(rpm, items, 'compatible', '"qcom,rpm-smd"')
    changes.append((
        items['qcom,glink-edge'][1], items['qcom,glink-edge'][2], ''))
    set_property(rpm, items, 'interrupts', '<0 0xa8 1>')
    set_property(rpm, items, 'rpm-channel-type', '<0xf>')

    smem = require_node('/soc/qcom,smem@86000000')
    items = properties(text, smem)
    require_value(items, 'compatible', '"qcom,smem"')
    require_cells(
        items, 'reg',
        [0x86000000, 0x200000, 0x17911008, 4,
         0x778000, 0x7000, 0x1fd4000, 8])
    if 'memory-region' in items or 'hwlocks' in items:
        raise ValueError('SMEM is already/partially patched')
    set_property(smem, items, 'memory-region', '<&smem_mem>')
    set_property(smem, items, 'hwlocks', '<&tcsr_mutex 3>')

    ramoops = require_node('/soc/ramoops')
    items = properties(text, ramoops)
    require_value(items, 'compatible', '"ramoops"')
    if 'reg' in items:
        require_cells(items, 'reg', [0xaf000000, 0xc0000])
    set_property(ramoops, items, 'reg', '<0xaf000000 0xc0000>')
    for key, value in (
            ('console-size', 0x40000),
            ('record-size', 0x3f800),
            ('pmsg-size', 0x40000)):
        require_cells(items, key, [0, value])
        set_property(ramoops, items, key, '<' + hex(value) + '>')

    changes.extend((
        (soc.closing, soc.closing, PROVIDERS),
        (reserved.closing, reserved.closing, SMEM_RESERVATION),
    ))
    for begin, end, replacement in sorted(
            changes, key=lambda item: item[:2], reverse=True):
        text = text[:begin] + replacement + text[end:]
    parse_nodes(text)
    return text


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('src', type=Path, help='stock evert DTS from dtc')
    parser.add_argument('dst', type=Path, help='patched output DTS')
    args = parser.parse_args(argv)
    temporary = None
    try:
        if args.src.resolve() == args.dst.resolve() or (
                args.dst.exists() and os.path.samefile(args.src, args.dst)):
            raise ValueError('input and output must be different files')

        result = patch(args.src.read_text(encoding='utf-8'))
        with tempfile.NamedTemporaryFile(
                mode='w', encoding='utf-8',
                dir=args.dst.parent, delete=False) as output:
            temporary = output.name
            output.write(result)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, args.dst)
        temporary = None
    except (OSError, ValueError) as error:
        parser.exit(1, 'error: ' + str(error) + '\n')
    finally:
        if temporary is not None:
            os.unlink(temporary)
    print('patched {} -> {}'.format(args.src, args.dst))


if __name__ == '__main__':
    main()