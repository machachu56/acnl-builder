"""Scripts -> a small program for the plugin's interpreter, with friendly errors.

A script is ordinary Python (a subset, see docs/SCRIPTING.md). It is never run by Python: it is read with `ast`,
checked against the project (does that building / outfit / villager exist?) and the game (is that address a function?)
and turned into bytecode. Every problem is reported with its line, a plain sentence and, when possible, a hint.
"""
import ast
import difflib
import struct

from . import actions as A

OPS = {ast.Add: 0, ast.Sub: 1, ast.Mult: 2, ast.FloorDiv: 3, ast.Mod: 4, ast.BitAnd: 11, ast.BitOr: 12, ast.BitXor: 13,
       ast.LShift: 14, ast.RShift: 15}
CMPS = {ast.Eq: 5, ast.NotEq: 6, ast.Lt: 7, ast.LtE: 8, ast.Gt: 9, ast.GtE: 10}
YAW = {"south": 0, "east": 16384, "north": 32768, "west": 49152}
MAX_CODE = 4000                 # bytes per handler
MAX_LOOP = 64
UNSUPPORTED = {
    ast.While: "`while` loops are not available (a script must always finish): use `for i in range(n):` with a fixed n",
    ast.Try: "`try` is not available: scripts have no exceptions",
    ast.ClassDef: "classes are not available: use functions",
    ast.Lambda: "`lambda` is not available: write a small `def`",
    ast.With: "`with` is not available",
    ast.Import: "only `from acnl import *` can be imported",
    ast.ImportFrom: "only `from acnl import *` can be imported",
    ast.Global: "`global` is not needed: use get_var(\"name\") and set_var(\"name\", value) to remember things",
    ast.Delete: "`del` is not available",
    ast.Assert: "`assert` is not available",
    ast.Raise: "`raise` is not available",
}


class Diag:
    def __init__(self, line, col, message, hint="", severity="error"):
        self.line, self.col, self.message, self.hint, self.severity = line, col, message, hint, severity

    def to_json(self):
        return {"line": self.line, "col": self.col, "severity": self.severity, "message": self.message, "hint": self.hint}

    def __str__(self):
        return "line %d: %s%s" % (self.line, self.message, (" (" + self.hint + ")") if self.hint else "")


class Stop(Exception):
    """abandon this statement (the error is already recorded)"""


class Ctx:
    """what the project and the game offer, for checking names"""

    def __init__(self, buildings=None, villagers=None, actors=None, is_function=None, variants=None, conversations=None):
        self.buildings = buildings or {}          # id -> [room ids (interior scene ids)]
        self.villagers = villagers or {}          # id -> [outfit ids]
        self.actors = {k.lower(): v for k, v in (actors or {}).items()}      # name -> profile id
        self.actor_names = dict(actors or {})
        self.is_function = is_function            # addr -> bool, or None when the code map is not available
        self.variants = variants or []
        self.conversations = conversations or []          # ids of events a script may switch on


class Handler:
    def __init__(self, kind, line, name):
        self.kind, self.line, self.name = kind, line, name
        self.s1 = self.s2 = 0xFFFF            # string indexes (building, room)
        self.num = 0                          # profile id / address
        self.code = bytearray()
        self.nlocals = 0


class Program:
    def __init__(self):
        self.strings, self.vars, self.handlers, self.diags = [], [], [], []

    def string(self, s):
        if s not in self.strings:
            self.strings.append(s)
        return self.strings.index(s)

    def var(self, name):
        if name not in self.vars:
            self.vars.append(name)
        return self.vars.index(name)

    @property
    def ok(self):
        return not any(d.severity == "error" for d in self.diags)

    def encode(self):
        out = bytearray(b"ACS1")
        out += struct.pack("<H", len(self.strings))
        for s in self.strings:
            b = s.encode("utf-8")[:255]
            out += bytes([len(b)]) + b
        out += struct.pack("<HH", len(self.vars), len(self.handlers))
        for h in self.handlers:
            out += struct.pack("<BHHIHH", A.KIND_CODE[h.kind], h.s1, h.s2, h.num & 0xFFFFFFFF, h.nlocals, len(h.code)) + bytes(h.code)
        return bytes(out)


def suggest(word, options, listall=True):
    m = difflib.get_close_matches(str(word), [str(o) for o in options], 1, 0.6)
    return "did you mean %r?" % m[0] if m else ("available: " + ", ".join(sorted(map(str, options))[:12]) if options and listall else "")


class Compiler:
    def __init__(self, ctx):
        self.ctx = ctx
        self.prog = Program()
        self.consts = {}
        self.helpers = {}
        self.h = None
        self.scope = None
        self.depth = 0
        self.inline_n = 0

    # ---- diagnostics
    def err(self, node, msg, hint="", severity="error"):
        self.prog.diags.append(Diag(getattr(node, "lineno", 0), getattr(node, "col_offset", 0), msg, hint, severity))
        raise Stop()

    def warn(self, node, msg, hint=""):
        self.prog.diags.append(Diag(getattr(node, "lineno", 0), getattr(node, "col_offset", 0), msg, hint, "warning"))

    # ---- emit
    def emit(self, *b):
        self.h.code += bytes(b)

    def op_push(self, v):
        self.h.code += b"\x01" + struct.pack("<i", int(v))

    def jump(self, op):
        self.h.code += bytes([op]) + b"\0\0"
        return len(self.h.code) - 2

    def patch(self, at, target=None):
        struct.pack_into("<H", self.h.code, at, len(self.h.code) if target is None else target)

    # ---- entry
    def compile(self, source):
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            self.prog.diags.append(Diag(e.lineno or 1, e.offset or 0, "this is not valid Python: %s" % e.msg, "check brackets, colons and indentation"))
            return self.prog
        for node in tree.body:
            try:
                self.top(node)
            except Stop:
                pass
        if not self.prog.handlers and self.prog.ok:
            self.prog.diags.append(Diag(1, 0, "the script has nothing to run yet", "add a function with a decorator such as @on_enter(\"my_building\")", "warning"))
        return self.prog

    def top(self, node):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return                                                           # docstring
        if isinstance(node, ast.ImportFrom):
            if node.module != "acnl" or [a.name for a in node.names] != ["*"]:
                self.err(node, "only `from acnl import *` can be imported")
            return
        if isinstance(node, ast.Assign):
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                self.err(node, "a top-level assignment must be `NAME = value`")
            v = self.const(node.value)
            self.consts[node.targets[0].id] = v
            return
        if isinstance(node, ast.FunctionDef):
            return self.function(node)
        if type(node) in UNSUPPORTED:
            self.err(node, UNSUPPORTED[type(node)])
        self.err(node, "only functions and constants can be written at the top of a script", "put the code inside a function with a decorator, e.g. @on_enter(\"building\")")

    def const(self, node):
        try:
            v = ast.literal_eval(node)
        except Exception:
            self.err(node, "a top-level constant must be a plain number or text")
        if isinstance(v, bool):
            return int(v)
        if isinstance(v, (int, str)):
            return v
        self.err(node, "a top-level constant must be a plain number or text")

    # ---- functions and triggers
    def function(self, fn):
        decos = fn.decorator_list
        if not decos:
            if fn.args.args == [] or all(a.arg for a in fn.args.args):
                self.helpers[fn.name] = fn
            return
        h = Handler("any", fn.lineno, fn.name)
        valid = True
        try:
            self.decorator(fn, decos, h)
        except Stop:
            valid = False
            d0 = decos[0]
            t = d0.func.id if isinstance(d0, ast.Call) and isinstance(d0.func, ast.Name) else getattr(d0, "id", None)
            h.kind = A.TRIGGERS[t][0] if t in A.TRIGGERS else "any"
        self.h, self.scope = h, {}
        self.kind = h.kind
        try:
            self.block(fn.body, tail=True)
            self.emit(0x0D)
            if len(h.code) > MAX_CODE:
                self.err(fn, "this function is too long for the game (%d bytes of code, at most %d)" % (len(h.code), MAX_CODE), "split it in smaller triggers")
            h.nlocals = len(self.scope)
            if h.nlocals > 32:
                self.err(fn, "too many local variables (%d, at most 32)" % h.nlocals)
            if valid:
                self.prog.handlers.append(h)
        finally:
            self.h = None

    def decorator(self, fn, decos, h):
        if len(decos) != 1:
            self.err(fn, "a function can have only one trigger decorator")
        d = decos[0]
        if not (isinstance(d, ast.Call) and isinstance(d.func, ast.Name)):
            name = d.id if isinstance(d, ast.Name) else "?"
            self.err(d, "%r needs its arguments in brackets" % name if name in A.TRIGGERS else "unknown trigger %r" % name, suggest(name, A.TRIGGERS))
        tname = d.func.id
        if tname not in A.TRIGGERS:
            self.err(d, "unknown trigger @%s" % tname, suggest(tname, A.TRIGGERS))
        h.kind = A.TRIGGERS[tname][0]
        if fn.args.args:
            self.err(fn, "a trigger function takes no parameters")
        kind, req, opt, _doc = A.TRIGGERS[tname]
        args = list(d.args)
        if len(args) < len(req) or len(args) > len(req) + (1 if opt else 0):
            self.err(d, "@%s needs %s" % (tname, ", ".join(n for n, _ in req)))
        kws = {k.arg: k.value for k in d.keywords}
        for k in kws:
            if k not in [n for n, _ in opt]:
                self.err(d, "@%s has no option %r" % (tname, k))
        building = None
        for (pn, pt), a in zip(req + opt, args + [None] * 3):
            if a is None and pn in kws:
                a = kws[pn]
            if a is None:
                continue
            if pt == "building":
                building = self.name_arg(a, "building", self.ctx.buildings)
                h.s1 = self.prog.string(building)
            elif pt == "room":
                r = self.name_arg(a, "room of %s" % building, self.ctx.buildings.get(building, []))
                h.s2 = self.prog.string(r)
            elif pt == "actor":
                h.num = self.actor_value(a)
            elif pt == "addr":
                v = a.value if isinstance(a, ast.Constant) else None
                if not isinstance(v, int) or isinstance(v, bool):
                    self.err(a, "the address must be a number, like 0x5c9380")
                if self.ctx.is_function and not self.ctx.is_function(v):
                    self.err(a, "0x%x is not the start of a function of the game" % v, "find addresses with `python3 -m acnlb map` (see docs/HOOKS.md)")
                h.num = v

    def name_arg(self, node, what, options):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            self.err(node, "the %s must be written as text, like \"name\"" % what)
        v = node.value
        if v not in options:
            self.err(node, "there is no %s %r in this project" % (what, v), suggest(v, options))
        return v

    def actor_value(self, node):
        if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            k = node.value.lower()
            if k in self.ctx.actors:
                return self.ctx.actors[k]
            self.err(node, "unknown actor %r" % node.value, suggest(node.value, self.ctx.actor_names, False) or "add it under Actors on the left (a name and the game's profile number; `python3 -m acnlb probe` lists the numbers)")
        self.err(node, "an actor is a name in quotes or its profile number")

    # ---- statements
    def block(self, body, tail=False):
        for i, st in enumerate(body):
            try:
                self.stmt(st, tail and i == len(body) - 1)
            except Stop:
                pass

    def local(self, name, create=False):
        if name not in self.scope:
            if not create:
                return None
            self.scope[name] = len(self.scope)
        return self.scope[name]

    def stmt(self, st, tail=False):
        if type(st) in UNSUPPORTED:
            self.err(st, UNSUPPORTED[type(st)])
        if isinstance(st, ast.Pass):
            return
        if isinstance(st, ast.Expr):
            if isinstance(st.value, ast.Constant):
                return
            returns = self.expr(st.value, want=False)
            if returns:
                self.emit(0x0C)
            return
        if isinstance(st, ast.Assign):
            if len(st.targets) != 1 or not isinstance(st.targets[0], ast.Name):
                self.err(st, "assign to one plain name: `x = ...`")
            self.expr(st.value)
            self.emit(0x03, self.local(self.mangle(st.targets[0].id), True))
            return
        if isinstance(st, ast.AugAssign):
            if not isinstance(st.target, ast.Name) or type(st.op) not in OPS:
                self.err(st, "use `x += value` with a plain name")
            slot = self.local(self.mangle(st.target.id))
            if slot is None:
                self.err(st, "%r has no value yet" % st.target.id, "give it one first: %s = 0" % st.target.id)
            self.emit(0x02, slot)
            self.expr(st.value)
            self.emit(0x06, OPS[type(st.op)])
            self.emit(0x03, slot)
            return
        if isinstance(st, ast.If):
            self.expr(st.test)
            j = self.jump(0x0A)
            self.block(st.body)
            if st.orelse:
                j2 = self.jump(0x09)
                self.patch(j)
                self.block(st.orelse)
                self.patch(j2)
            else:
                self.patch(j)
            return
        if isinstance(st, ast.For):
            return self.for_loop(st)
        if isinstance(st, ast.Return):
            if self.depth:
                if not tail:
                    self.err(st, "`return` inside a helper must be its last line")
                return
            if st.value is not None:
                self.err(st, "a trigger function cannot return a value")
            self.emit(0x0D)
            return
        if isinstance(st, (ast.Break, ast.Continue)):
            self.err(st, "`break` and `continue` are not available")
        self.err(st, "this kind of statement is not available in scripts")

    def mangle(self, name):
        return name if not self.depth else "%s@%d" % (name, self.inline_n)

    def for_loop(self, st):
        it = st.iter
        if not (isinstance(st.target, ast.Name) and isinstance(it, ast.Call) and isinstance(it.func, ast.Name) and it.func.id == "range"
                and 1 <= len(it.args) <= 2 and not st.orelse):
            self.err(st, "only `for i in range(n):` or `range(a, b)` loops are available")
        vals = [self.static_int(a) for a in it.args]
        lo, hi = (0, vals[0]) if len(vals) == 1 else vals
        if hi - lo > MAX_LOOP:
            self.err(st, "this loop would run %d times; at most %d" % (hi - lo, MAX_LOOP))
        slot = self.local(self.mangle(st.target.id), True)
        end = self.local("%s#end%d" % (st.target.id, len(self.scope)), True)
        self.op_push(lo)
        self.emit(0x03, slot)
        self.op_push(hi)
        self.emit(0x03, end)
        top = len(self.h.code)
        self.emit(0x02, slot)
        self.emit(0x02, end)
        self.emit(0x06, 7)
        j = self.jump(0x0A)
        self.block(st.body)
        self.emit(0x02, slot)
        self.op_push(1)
        self.emit(0x06, 0)
        self.emit(0x03, slot)
        jb = self.jump(0x09)
        self.patch(jb, top)
        self.patch(j)

    def static_int(self, node):
        try:
            v = ast.literal_eval(node)
        except Exception:
            v = self.consts.get(node.id) if isinstance(node, ast.Name) else None
        if not isinstance(v, int):
            self.err(node, "the size of a loop must be a fixed number")
        return v

    # ---- expressions: emit code; return True if a value was pushed
    def expr(self, n, want=True):
        if isinstance(n, ast.Constant):
            v = n.value
            if isinstance(v, bool) or isinstance(v, int):
                self.op_push(int(v))
                return True
            if v is None:
                self.op_push(0)
                return True
            self.err(n, "text can only be given to a function that expects text, like log(\"...\")")
        if isinstance(n, ast.Name):
            slot = self.local(self.mangle(n.id))
            if slot is not None:
                self.emit(0x02, slot)
                return True
            if n.id in self.consts and isinstance(self.consts[n.id], int):
                self.op_push(self.consts[n.id])
                return True
            if n.id in self.consts:
                self.err(n, "%r is text; it can only be given to a function that expects text" % n.id)
            self.err(n, "%r is not defined" % n.id, suggest(n.id, list(self.scope) + list(self.consts), True) if (self.scope or self.consts) else "remember values with set_var(\"name\", value) and read them with get_var(\"name\")")
        if isinstance(n, ast.BinOp):
            if isinstance(n.op, ast.Div):
                self.err(n, "`/` is not available: use `//` for whole-number division")
            if type(n.op) not in OPS:
                self.err(n, "this operator is not available")
            self.expr(n.left)
            self.expr(n.right)
            self.emit(0x06, OPS[type(n.op)])
            return True
        if isinstance(n, ast.UnaryOp):
            self.expr(n.operand)
            if isinstance(n.op, ast.Not):
                self.emit(0x07)
            elif isinstance(n.op, ast.USub):
                self.emit(0x08)
            elif isinstance(n.op, ast.UAdd):
                pass
            else:
                self.err(n, "this operator is not available")
            return True
        if isinstance(n, ast.BoolOp):
            ends = []
            for i, v in enumerate(n.values):
                self.expr(v)
                if i < len(n.values) - 1:
                    self.emit(0x0E)
                    ends.append(self.jump(0x0A if isinstance(n.op, ast.And) else 0x0F))
                    self.emit(0x0C)
            for e in ends:
                self.patch(e)
            return True
        if isinstance(n, ast.Compare):
            if len(n.ops) != 1 or type(n.ops[0]) not in CMPS:
                self.err(n, "compare two values with ==, !=, <, <=, >, >=; for a range write `a < x and x < b`")
            self.expr(n.left)
            self.expr(n.comparators[0])
            self.emit(0x06, CMPS[type(n.ops[0])])
            return True
        if isinstance(n, ast.IfExp):
            self.expr(n.test)
            j = self.jump(0x0A)
            self.expr(n.body)
            j2 = self.jump(0x09)
            self.patch(j)
            self.expr(n.orelse)
            self.patch(j2)
            return True
        if isinstance(n, ast.Call):
            return self.call(n, want)
        self.err(n, "this kind of expression is not available in scripts")

    def minutes(self, node):
        text = node.value if isinstance(node, ast.Constant) else self.consts.get(node.id) if isinstance(node, ast.Name) else None
        if not isinstance(text, str):
            self.err(node, "write the time as text like \"22:30\" (or a constant holding such text)")
        try:
            h, m = text.split(":")
            h, m = int(h), int(m)
            assert 0 <= h < 24 and 0 <= m < 60
        except Exception:
            self.err(node, "%r is not a time" % text, "use 24-hour \"HH:MM\", e.g. \"06:00\"")
        return h * 60 + m

    def call(self, n, want):
        if not isinstance(n.func, ast.Name):
            self.err(n, "only plain function calls are available")
        name = n.func.id
        if n.keywords:
            self.err(n, "give arguments in order, without names")
        if name == "time_between":
            if len(n.args) != 2:
                self.err(n, "time_between(start, end) takes two times, e.g. time_between(\"22:00\", \"06:00\")")
            a, b = self.minutes(n.args[0]), self.minutes(n.args[1])
            now = lambda: (self.emit(0x0B, 0, 0), self.op_push(60), self.emit(0x06, 2), self.emit(0x0B, 1, 0), self.emit(0x06, 0))
            now(); self.op_push(a); self.emit(0x06, 10)
            now(); self.op_push(b); self.emit(0x06, 7)
            self.emit(0x06, 11 if a <= b else 12)
            return True
        if name in self.helpers:
            return self.inline(n, want)
        nat = A.BY_NAME.get(name)
        if nat is None:
            self.err(n, "unknown function %r" % name, suggest(name, list(A.BY_NAME) + list(self.helpers) + ["time_between"]))
        if "any" not in nat.where and self.kind not in nat.where:
            self.err(n, "%s() can only be used in %s" % (name, " or ".join("@on_" + w for w in nat.where)),
                     "it belongs to a different kind of trigger")
        required = [p for p in nat.params if not p[1].endswith("?")]
        if not (len(required) <= len(n.args) <= len(nat.params)):
            self.err(n, "%s(%s) takes %s" % (name, ", ".join(p[0] for p in nat.params), "%d value(s)" % len(nat.params) if len(required) == len(nat.params) else "%d to %d values" % (len(required), len(nat.params))))
        building = None
        for (pn, pt), a in zip(nat.params, n.args):
            pt = pt.rstrip("?")
            if pt in ("int", "bool"):
                self.expr(a)
            elif pt == "str":
                if not (isinstance(a, ast.Constant) and isinstance(a.value, str)):
                    self.err(a, "%s expects text in quotes here" % pn)
                if pn == "facing":
                    if a.value not in YAW:
                        self.err(a, "facing must be \"north\", \"south\", \"east\" or \"west\"")
                    self.op_push(YAW[a.value])
                else:
                    self.op_push(self.prog.string(a.value) if name not in ("get_var", "set_var") else self.prog.var(a.value))
            elif pt == "building":
                building = self.name_arg(a, "building", self.ctx.buildings)
                self.op_push(self.prog.string(building))
            elif pt == "room":
                r = self.name_arg(a, "room of %s" % building, self.ctx.buildings.get(building, []))
                self.op_push(self.prog.string(r))
            elif pt == "conversation":
                cv = self.name_arg(a, "conversation (Events tab, “only when a script turns it on”)", self.ctx.conversations)
                self.op_push(self.prog.string("ev_" + cv))
            elif pt == "villager":
                self.vill = self.name_arg(a, "villager", self.ctx.villagers)
                self.op_push(self.prog.string(self.vill))
            elif pt == "outfit":
                o = self.name_arg(a, "outfit of %s" % self.vill, self.ctx.villagers.get(self.vill, []))
                self.op_push(self.prog.string(o))
            elif pt == "actor":
                self.op_push(self.actor_value(a))
        for _ in range(len(nat.params) - len(n.args)):
            self.op_push(0)                                  # optional values default to 0
        self.emit(0x0B, {30: 15, 31: 16}.get(nat.id, nat.id), len(nat.params))        # conversation_on/off are variant_on/off of the event's variant
        return nat.returns is not None

    def inline(self, n, want):
        fn = self.helpers[n.func.id]
        params = [a.arg for a in fn.args.args]
        if len(n.args) != len(params):
            self.err(n, "%s takes %d value(s)" % (fn.name, len(params)))
        if self.depth >= 4:
            self.err(n, "helpers are nested too deeply (a helper cannot call itself)")
        self.inline_n += 1
        self.depth += 1
        tag = self.inline_n
        try:
            for p, a in zip(params, n.args):
                self.expr(a)
                self.emit(0x03, self.local("%s@%d" % (p, tag), True))
            body = [b for b in fn.body if not (isinstance(b, ast.Expr) and isinstance(b.value, ast.Constant))]
            if body and isinstance(body[-1], ast.Return) and body[-1].value is not None:
                self.block(body[:-1])
                self.expr(body[-1].value)
                return True
            self.block(body, tail=True)
            return False
        finally:
            self.depth -= 1
            self.inline_n = tag


def compile_source(source, ctx=None):
    return Compiler(ctx or Ctx()).compile(source)
