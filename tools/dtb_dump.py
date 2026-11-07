#!/usr/bin/env python3
"""Small FDT dumper for boot-image / kernel DTB inspection."""
import struct
import sys

FDT_BEGIN_NODE = 1
FDT_END_NODE = 2
FDT_PROP = 3
FDT_NOP = 4
FDT_END = 9


def cstr(buf, off):
    end = buf.find(b"\0", off)
    if end < 0:
        return buf[off:].decode("utf-8", "replace")
    return buf[off:end].decode("utf-8", "replace")


def parse(path):
    data = open(path, "rb").read()
    (magic, totalsize, off_struct, off_strings, off_rsv, version,
     last_comp, boot_cpuid, size_strings, size_struct) = struct.unpack_from(">10I", data, 0)
    if magic != 0xD00DFEED:
        raise SystemExit(f"{path}: bad FDT magic {magic:#x}")
    strings = data[off_strings:off_strings + size_strings]
    pos = off_struct
    stack = []
    nodes = {}
    while True:
        tok = struct.unpack_from(">I", data, pos)[0]
        pos += 4
        if tok == FDT_BEGIN_NODE:
            end = data.find(b"\0", pos)
            name = data[pos:end].decode("utf-8", "replace")
            pos = (end + 1 + 3) & ~3
            stack.append(name)
        elif tok == FDT_END_NODE:
            stack.pop()
        elif tok == FDT_PROP:
            length, nameoff = struct.unpack_from(">II", data, pos)
            pos += 8
            value = data[pos:pos + length]
            pos = (pos + length + 3) & ~3
            path = "/" + "/".join(x for x in stack if x)
            nodes.setdefault(path, {})[cstr(strings, nameoff)] = value
        elif tok == FDT_NOP:
            continue
        elif tok == FDT_END:
            break
        else:
            raise SystemExit(f"{path}: bad token {tok:#x} at {pos - 4:#x}")
    return data, nodes


def fmt_prop(name, value):
    if name in ("compatible", "model", "status", "stdout-path"):
        return repr(value.rstrip(b"\0").decode("utf-8", "replace"))
    if name in ("qcom,board-id", "qcom,msm-id", "qcom,pmic-id", "reg"):
        if len(value) % 4 == 0:
            vals = struct.unpack(">" + "I" * (len(value) // 4), value)
            return " ".join(f"{v:#x}" for v in vals)
    if len(value) <= 32:
        return value.hex()
    return f"<{len(value)} bytes>"


def main():
    if len(sys.argv) < 2:
        raise SystemExit(f"usage: {sys.argv[0]} DTB [compatible-substring ...]")
    for path in sys.argv[1:]:
        if not path.endswith((".dtb", ".img")):
            continue
        data, nodes = parse(path)
        print(f"===== {path} ({len(data)} bytes, {len(nodes)} nodes)")
        for node in sorted(nodes):
            props = nodes[node]
            compat = props.get("compatible", b"").rstrip(b"\0").decode("utf-8", "replace")
            model = props.get("model", b"").rstrip(b"\0").decode("utf-8", "replace")
            status = props.get("status", b"").rstrip(b"\0").decode("utf-8", "replace")
            if node in ("/", "/chosen", "/memory", "/reserved-memory") or compat:
                print(f"{node}: model={model!r} compatible={compat!r} status={status!r}")
                for k in ("qcom,board-id", "qcom,msm-id", "qcom,pmic-id", "reg", "bootargs",
                          "stdout-path"):
                    if k in props:
                        print(f"    {k} = {fmt_prop(k, props[k])}")


if __name__ == "__main__":
    main()
