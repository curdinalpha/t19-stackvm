"""Tests for vm_solution.py (stdlib unittest, no network, no deps).
Run: python3.12 -m unittest -v test_vm.py"""
import ast, json, os, random, struct, unittest
from vm_solution import VM, VMError, asm, OP, GAS, FACT, LOOP

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'vm_solution.py')
H = 1 << 63


def run(src, gas=10**6, steps=-1):
    v = VM(asm(src), gas)
    v.run(steps)
    return v


def state(v):
    return (v.ip, list(v.st), list(v.fr), v.gas, v.steps, v.status)


class Spec(unittest.TestCase):
    def test_single_file_size_limit(self):
        n = os.path.getsize(SRC)
        self.assertLessEqual(n, 4096, n)

    def test_stdlib_only_imports(self):
        with open(SRC, encoding='utf-8') as f:
            tree = ast.parse(f.read())
        mods = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods |= {a.name.split('.')[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                mods.add(node.module.split('.')[0])
        self.assertLessEqual(mods, {'json', 'hashlib', 'struct', 'sys', 'time'})

    def test_bytecode_encoding(self):
        code = asm('PUSH -2; JMP 0; HALT')
        self.assertEqual(code, bytes([OP['PUSH']]) + struct.pack('<i', -2)
                         + bytes([OP['JMP']]) + struct.pack('<i', 0) + bytes([0]))
        self.assertIsInstance(code, bytes)


class Arithmetic(unittest.TestCase):
    def test_basic_ops(self):
        cases = {'PUSH 7;PUSH 5;ADD': 12, 'PUSH 7;PUSH 5;SUB': 2,
                 'PUSH 7;PUSH 5;MUL': 35, 'PUSH 7;PUSH 2;DIV': 3,
                 'PUSH 7;PUSH 3;MOD': 1, 'PUSH 7;NEG': -7,
                 'PUSH 3;PUSH 3;EQ': 1, 'PUSH 3;PUSH 4;EQ': 0,
                 'PUSH 3;PUSH 4;LT': 1, 'PUSH 4;PUSH 3;LT': 0,
                 'PUSH 4;PUSH 3;GT': 1, 'PUSH -1;PUSH 0;GT': 0}
        for src, want in cases.items():
            with self.subTest(src=src):
                v = run(src + ';HALT')
                self.assertEqual((v.st, v.status), ([want], 'HALT'))

    def test_signed_division_truncates_toward_zero(self):
        for a, b, q, r in [(7, 2, 3, 1), (-7, 2, -3, -1), (7, -2, -3, 1), (-7, -2, 3, -1)]:
            self.assertEqual(run(f'PUSH {a};PUSH {b};DIV;HALT').st, [q])
            self.assertEqual(run(f'PUSH {a};PUSH {b};MOD;HALT').st, [r])

    def test_i64_wraparound(self):
        # 2^31-1 squared repeatedly overflows i64 and must wrap deterministically
        v = run('PUSH 2147483647;DUP;MUL;DUP;MUL;HALT')
        x = ((2**31 - 1) ** 2) % 2**64
        x = ((x if x < H else x - 2**64) ** 2 + H) % 2**64 - H
        self.assertEqual(v.st, [x])
        self.assertTrue(-H <= v.st[0] < H)
        v = VM(asm('NEG;HALT')); v.st = [-H]; v.run()
        self.assertEqual(v.st, [-H])  # -INT64_MIN wraps to itself
        v = VM(asm('PUSH -1;DIV;HALT')); v.st = [-H]; v.run()
        self.assertEqual(v.st, [-H])

    def test_stack_ops(self):
        self.assertEqual(run('PUSH 1;PUSH 2;SWAP;HALT').st, [2, 1])
        self.assertEqual(run('PUSH 1;PUSH 2;OVER;HALT').st, [1, 2, 1])
        self.assertEqual(run('PUSH 1;DUP;HALT').st, [1, 1])
        self.assertEqual(run('PUSH 1;PUSH 2;POP;HALT').st, [1])


class ControlFlow(unittest.TestCase):
    def test_relative_jumps_forward_and_backward(self):
        # sum 1..10 with a backward JNZ loop
        v = run('PUSH 0;PUSH 10;l: SWAP;OVER;ADD;SWAP;PUSH 1;SUB;DUP;JNZ l;POP;HALT')
        self.assertEqual(v.st, [55])
        v = run('PUSH 0;JZ s;PUSH 99;s: PUSH 1;HALT')
        self.assertEqual(v.st, [1])
        v = run('PUSH 5;JZ s;PUSH 99;s: PUSH 1;HALT')
        self.assertEqual(v.st, [99, 1])

    def test_raw_relative_offset_is_from_next_instruction(self):
        # JMP +1 skips exactly one 1-byte POP
        v = run('PUSH 4;PUSH 5;JMP 1;POP;HALT')
        self.assertEqual(v.st, [4, 5])

    def test_call_ret_recursive_factorial(self):
        v = VM(FACT); self.assertEqual(v.run(), 'HALT')
        self.assertEqual(v.st, [479001600]); self.assertEqual(v.fr, [])

    def test_nested_calls_keep_partial_operand_stack(self):
        v = run('PUSH 1;PUSH 2;CALL a;ADD;HALT;a: PUSH 10;CALL b;MUL;RET;b: PUSH 3;RET')
        self.assertEqual(v.st, [1, 32])

    def test_yield_and_resume(self):
        v = VM(asm('PUSH 1;YIELD;PUSH 2;YIELD;ADD;HALT'))
        self.assertEqual(v.run(), 'YIELD'); self.assertEqual(v.st, [1])
        self.assertEqual(v.run(), 'YIELD'); self.assertEqual(v.st, [1, 2])
        self.assertEqual(v.run(), 'HALT'); self.assertEqual(v.st, [3])
        self.assertEqual(v.run(), 'HALT')

    def test_falling_off_end_halts(self):
        v = run('PUSH 1')
        self.assertEqual((v.status, v.st), ('HALT', [1]))


class Gas(unittest.TestCase):
    def test_gas_is_per_opcode_table(self):
        v = run('PUSH 6;PUSH 7;MUL;HALT')
        self.assertEqual(10**6 - v.gas, GAS[OP['PUSH']] * 2 + GAS[OP['MUL']] + GAS[OP['HALT']])
        self.assertEqual(v.steps, 4)

    def test_gas_deterministic_across_runs(self):
        a, b = VM(LOOP, 10**8), VM(LOOP, 10**8)
        a.run(); b.run()
        self.assertEqual(state(a), state(b))
        self.assertEqual(a.steps, 3600006)

    def test_out_of_gas_is_atomic_and_resumable(self):
        full = VM(FACT); full.run()
        v = VM(FACT, 50)
        self.assertEqual(v.run(), 'OOG')
        before = state(v)
        self.assertEqual(v.run(), 'OOG')  # no progress, nothing mutated
        self.assertEqual(state(v), before)
        v.gas += 10**6 - 50
        self.assertEqual(v.run(), 'HALT')
        self.assertEqual(state(v), state(full))

    def test_oog_checkpoint_topup(self):
        v = VM(FACT, 77); v.run()
        blob = json.loads(VM.restore(FACT, v.checkpoint()).checkpoint())
        blob['gas'] += 10**6
        w = VM.restore(FACT, json.dumps(blob)); self.assertEqual(w.run(), 'HALT')
        self.assertEqual(w.st, [479001600])


class Checkpoint(unittest.TestCase):
    def test_roundtrip_is_byte_identical(self):
        v = VM(FACT); v.run(40)
        cp = v.checkpoint()
        self.assertEqual(VM.restore(FACT, cp).checkpoint(), cp)
        d = json.loads(cp)
        self.assertEqual(d['status'], 'PAUSE')
        self.assertGreater(len(d['fr']), 1)  # mid-call
        self.assertGreater(len(d['st']), 1)  # partial operand stack

    def test_checkpoint_at_every_instruction_boundary(self):
        full = VM(FACT); full.run()
        for i in range(full.steps + 1):
            v = VM(FACT); v.run(i)
            w = VM.restore(FACT, v.checkpoint())
            self.assertEqual(state(w), state(v))
            w.run()
            self.assertEqual(vars(w), vars(full), i)

    def test_chained_single_step_fiber(self):
        full = VM(FACT); full.run()
        cp, n = VM(FACT).checkpoint(), 0
        while True:
            v = VM.restore(FACT, cp)
            r = v.run(1)
            cp, n = v.checkpoint(), n + 1
            if r == 'HALT':
                break
        self.assertEqual(vars(VM.restore(FACT, cp)), vars(full))
        self.assertEqual(n, full.steps)

    def test_resume_on_wrong_code_rejected(self):
        v = VM(FACT); v.run(10)
        with self.assertRaises(VMError):
            VM.restore(LOOP, v.checkpoint())

    def test_corrupt_checkpoints_rejected(self):
        v = VM(FACT); v.run(40)
        good = json.loads(v.checkpoint())
        bad = [dict(good, ip=1), dict(good, ip=-1), dict(good, fr=[3]),
               dict(good, st=[2**63]), dict(good, st=['x']), dict(good, gas=-1),
               dict(good, gas=1.5), dict(good, status='WEIRD'), dict(good, v=2),
               dict(good, steps=None), {k: x for k, x in good.items() if k != 'fr'}]
        for b in bad:
            with self.subTest(b=b), self.assertRaises(VMError):
                VM.restore(FACT, json.dumps(b))
        for raw in (b'', b'not json', b'[]', b'{"v":1}'):
            with self.assertRaises(VMError):
                VM.restore(FACT, raw)

    def test_checkpoint_does_not_alias_live_state(self):
        v = VM(FACT); v.run(30)
        cp = v.checkpoint(); v.run()
        self.assertEqual(json.loads(cp)['steps'], 30)
        w = VM.restore(FACT, cp); w.run()
        self.assertEqual(w.st, v.st)


class Faults(unittest.TestCase):
    def check_fault(self, src, msg, gas=10**6):
        v = VM(asm(src), gas)
        with self.assertRaisesRegex(VMError, msg):
            v.run()
        self.assertEqual(v.status, 'FAULT')
        self.assertEqual(v.run(), 'FAULT')
        return v

    def test_underflow(self):
        v = self.check_fault('PUSH 1;ADD', 'underflow')
        self.assertEqual((v.st, v.ip), ([1], 5))  # faulting op not applied

    def test_div_and_mod_by_zero_atomic(self):
        v = self.check_fault('PUSH 1;PUSH 0;DIV', 'div by 0')
        self.assertEqual(v.st, [1, 0])
        self.check_fault('PUSH 1;PUSH 0;MOD', 'div by 0')

    def test_ret_without_frame(self):
        self.check_fault('RET', 'no frame')

    def test_call_depth_limit(self):
        self.check_fault('f: CALL f', 'call depth', gas=10**7)

    def test_stack_overflow_limit(self):
        self.check_fault('l: PUSH 1;JMP l', 'overflow', gas=10**7)

    def test_bad_bytecode_rejected_at_load(self):
        for code in (bytes([200]), bytes([OP['PUSH'], 1, 2]),
                     asm('JMP 2;HALT'), asm('JMP -100;HALT'),
                     bytes([OP['JMP']]) + struct.pack('<i', 2) + bytes([OP['PUSH']]) + b'\0\0\0\0'):
            with self.subTest(code=code), self.assertRaises(VMError):
                VM(code)


def random_program(rng):
    """Random valid program using labels so all jump targets land on boundaries."""
    names = ['PUSH', 'POP', 'DUP', 'SWAP', 'OVER', 'ADD', 'SUB', 'MUL', 'DIV',
             'MOD', 'NEG', 'EQ', 'LT', 'GT', 'JMP', 'JZ', 'JNZ', 'CALL', 'RET', 'YIELD']
    n = rng.randint(3, 30)
    lines = []
    for i in range(n):
        op = rng.choice(names + ['PUSH'] * 4)
        if op == 'PUSH':
            arg = ' %d' % rng.choice([rng.randint(-9, 9), rng.randint(-2**31, 2**31 - 1)])
        elif op in ('JMP', 'JZ', 'JNZ', 'CALL'):
            arg = ' L%d' % rng.randint(0, n)
        else:
            arg = ''
        lines.append('L%d: %s%s' % (i, op, arg))
    lines.append('L%d: HALT' % n)
    return asm(';'.join(lines))


def drive(code, gas, chunks):
    """Run to completion; if chunks is a Random, checkpoint/restore between random slices."""
    v = VM(code, gas)
    while True:
        try:
            if chunks is None:
                r = v.run()
            else:
                r = v.run(chunks.randint(0, 7))
                v = VM.restore(code, v.checkpoint())
        except VMError as e:
            return ('FAULT', str(e), state(v))
        if r in ('HALT', 'OOG'):
            return (r, state(v))


class Fuzz(unittest.TestCase):
    def test_random_programs_checkpointing_is_transparent(self):
        rng = random.Random(19)
        outcomes = set()
        for _ in range(600):
            code = random_program(rng)
            gas = rng.randint(1, 400)
            want = drive(code, gas, None)
            got = drive(code, gas, random.Random(rng.random()))
            self.assertEqual(got, want)
            outcomes.add(want[0])
        self.assertEqual(outcomes, {'HALT', 'OOG', 'FAULT'})


if __name__ == '__main__':
    unittest.main()
