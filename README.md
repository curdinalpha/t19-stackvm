# t19-stackvm — <=4 KB Python 3.12 bytecode stack VM with fiber checkpoints

Entry for Stellarator Yard DISPATCH-02, task `t=19`
(issue: https://github.com/incidere/solana-agent-bounties/issues/2).

`vm_solution.py` is a single file, **4056 bytes** (limit 4096, check with `wc -c`),
pure Python 3.12 standard library (`json hashlib struct sys time`). No deps, no network.

## Run

```sh
wc -c vm_solution.py                        # 4056
python3.12 vm_solution.py                   # benchmark + checkpoint round-trip demo (one JSON line)
python3.12 -m unittest -v test_vm.py        # 30 tests
unshare -rn python3.12 -m unittest test_vm.py   # optional: same run with no network namespace
```

## Design

* **Real bytecode.** Each op is 1 byte; `PUSH/JMP/JZ/JNZ/CALL` carry a 4-byte little-endian
  signed operand. Jump/call offsets are relative to the next instruction. The code is decoded
  and checked once at load: unknown opcodes, truncated operands and jump targets that don't land
  on an instruction boundary raise `VMError`. `asm()` is a tiny assembler with `label:` support.
* **ISA (21 ops):** `HALT PUSH POP DUP SWAP OVER ADD SUB MUL DIV MOD NEG EQ LT GT JMP JZ JNZ CALL RET YIELD`.
* **Integers:** signed 64-bit, wrapping (two's complement). `DIV` truncates toward zero, `MOD`
  takes the sign of the dividend (C semantics). Divide by zero is a fault.
* **Frames:** `CALL` pushes the return address on a separate call stack (depth limit 1024);
  `RET` pops it. Operand stack is shared (Forth style), so a callee can leave results for its caller.
* **Gas:** fixed per-opcode table (`GAS`, MUL=2, DIV/MOD=3, CALL=3, RET=2, others 1). Gas is
  checked before an op runs; if it's short the VM stops with `OOG` without touching any state,
  and you can top up `vm.gas` (or the checkpoint) and continue.
* **Faults are atomic:** underflow, overflow (65536 cells), div by zero, bad RET and call depth
  are detected before the op mutates anything; status becomes `FAULT` and `ip` points at the
  faulting op.
* **Fibers:** `run(steps)` executes at most `steps` instructions (interrupt → `PAUSE`); `YIELD`
  suspends from inside the program. Statuses: `READY PAUSE YIELD OOG HALT FAULT`. Running off
  the end of the code is a normal `HALT`.
* **Checkpoints:** `vm.checkpoint()` returns compact canonical JSON bytes with format version,
  a SHA-256 prefix of the bytecode, `ip`, operand stack, call frames, gas, step count and status.
  `VM.restore(code, blob)` refuses checkpoints taken on different code and validates every field
  (ip/frames must be instruction boundaries, stack cells must be i64 ints, etc.); any malformed
  blob raises `VMError`. Re-checkpointing a restored VM gives byte-identical output.

## What the tests check

Size limit and stdlib-only imports (parsed with `ast`), byte encoding, every opcode, signed
division/modulo, i64 wrap edge cases, forward/backward jumps, raw relative offsets, recursive
factorial via CALL/RET, nested calls with a partial operand stack, YIELD/resume, per-op gas
accounting, gas determinism, OOG atomicity and top-up (live and via checkpoint), checkpoint at
**every** instruction boundary of `fact(12)` and resuming to a state identical to the
uninterrupted run (`vars()` equality), a fully chained one-step-per-restore fiber, wrong-code
and corrupted checkpoint rejection, each fault type, invalid bytecode at load, and a seeded fuzz
test: 600 random programs, run straight vs. sliced into random chunks with a checkpoint/restore
between every chunk; outcomes (HALT/OOG/FAULT, final state, fault message) must be identical.

## Benchmark

`python3.12 vm_solution.py` runs a 400000-iteration loop (3,600,006 instructions) and prints
ops/sec. Real output is in `evidence/` (about 6.0–6.2M ops/sec on the build box;
your number will depend on the machine).
