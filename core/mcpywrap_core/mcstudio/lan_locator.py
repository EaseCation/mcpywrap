"""识别 NetherNet TransportConfiguration 的默认 LAN 端口，不保存版本地址表。"""
from bisect import bisect_right
from dataclasses import dataclass
import re
import struct


class LocatorError(ValueError):
    pass


@dataclass(frozen=True)
class PortSite:
    instruction_rva: int
    operand_rva: int
    function_rva: int
    expected: bytes


def locate_port(image):
    """image 提供 sections、functions 和 read(rva, size)，可用于静态夹具和活动映像。

    从 Windows x64 展开表确定指令边界，再识别端口、广播周期及协议 magic
    的同一栈对象初始化。必须恰好找到一处；不把 CALL 位移或数据中的 7551 当指令。
    """
    from capstone import Cs, CS_ARCH_X86, CS_MODE_64
    from capstone.x86_const import X86_OP_IMM, X86_OP_MEM, X86_OP_REG
    decoder = Cs(CS_ARCH_X86, CS_MODE_64)
    decoder.detail = True
    functions = sorted(image.functions)
    starts = [start for start, end in functions]
    seen, candidates = set(), []
    for rva, size, executable in image.sections:
        if not executable:
            continue
        code = image.read(rva, size)
        for match in re.finditer(re.escape(struct.pack('<I', 7551)), code):
            position = rva + match.start()
            index = bisect_right(starts, position) - 1
            if index < 0:
                continue
            start, end = functions[index]
            if not start <= position < end or end-start > 32768 or start in seen:
                continue
            seen.add(start)
            instructions = list(decoder.disasm(image.read(start, end-start), start))
            if not instructions or instructions[-1].address + instructions[-1].size != end:
                continue
            for i, instruction in enumerate(instructions[:-1]):
                operands = instruction.operands
                if (instruction.mnemonic != 'mov' or len(operands) != 2 or
                        operands[0].type != X86_OP_REG or operands[0].size != 4 or
                        operands[1].type != X86_OP_IMM or operands[1].imm != 7551 or
                        instruction.imm_size != 4):
                    continue
                store = instructions[i+1]
                if (store.mnemonic != 'mov' or len(store.operands) != 2 or
                        store.operands[0].type != X86_OP_MEM or store.operands[0].size != 2 or
                        store.operands[1].type != X86_OP_REG):
                    continue
                # 本组配置的 port 在 magic 后 8 字节，interval 紧接 port 后 4 字节。
                port = store.operands[0].mem
                register = instruction.reg_name(operands[0].reg)
                low_register = store.reg_name(store.operands[1].reg)
                aliases = {'eax': 'ax', 'ebx': 'bx', 'ecx': 'cx', 'edx': 'dx',
                           'esi': 'si', 'edi': 'di', **{'r%sd' % n: 'r%sw' % n for n in range(8,16)}}
                if aliases.get(register) != low_register or store.reg_name(port.base) not in ('rsp','rbp') or port.index:
                    continue
                interval, magic, passed = False, False, False
                magic_register = None
                for following in instructions[i+2:i+35]:
                    ops = following.operands
                    if following.mnemonic == 'mov' and len(ops) == 2:
                        if (ops[0].type == X86_OP_MEM and ops[0].mem.base == port.base and
                                ops[0].mem.disp == port.disp+4 and ops[1].type == X86_OP_IMM and ops[1].imm == 2000):
                            interval = True
                        if ops[0].type == X86_OP_REG and ops[1].type == X86_OP_IMM and ops[1].imm == 0xdeadbeef:
                            magic_register = following.reg_name(ops[0].reg)
                        if (ops[0].type == X86_OP_MEM and ops[0].mem.base == port.base and
                                ops[0].mem.disp == port.disp-8 and ops[1].type == X86_OP_REG and
                                magic_register and following.reg_name(ops[1].reg) in
                                (magic_register, magic_register[:-1] if magic_register.startswith('r') and magic_register.endswith('d') else 'r'+magic_register[1:])):
                            magic = True
                    if (following.mnemonic == 'lea' and len(ops) == 2 and
                            ops[0].type == X86_OP_REG and following.reg_name(ops[0].reg) == 'rcx' and
                            ops[1].type == X86_OP_MEM and ops[1].mem.base == port.base and
                            ops[1].mem.disp == port.disp-8):
                        passed = True
                if interval and magic and passed:
                    candidates.append(PortSite(instruction.address, instruction.address+instruction.imm_offset,
                                               start, bytes(instruction.bytes)))
    if len(candidates) != 1:
        raise LocatorError('无法唯一识别 NetherNet LAN 配置初始化（候选数：%s）。' % len(candidates))
    return candidates[0]
