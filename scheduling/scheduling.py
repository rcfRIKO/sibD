"""
Usage guide:

Input needs to be in this format:
input_schedule = 'r2(x) r1(y) w3(x) w2(x) r3(y) w3(y) w2(y) w2(z) a2 r1(z) w1(z) c1 w3(z) c3'

Try to adjust the `parse` yourself if this does not work.

Use
> c2pl(input_schedule)
or
> s2pl(input_schedule)      # optionally pass strict=True as a keyword argument
to apply the scheduling method.

To check for recoverability of the schedule (i.e. if it is in ST, ACA or RC) use
> recoverable(input_schedule)

Don't blame me if something is not correct :)
"""
from collections import namedtuple, defaultdict
from itertools import chain
import re

schedule_input = 'r2(x) r1(y) w3(x) w2(x) r3(y) w3(y) w2(y) w2(z) a2 r1(z) w1(z) c1 w3(z) c3'

Op = namedtuple('Op', ['action', 'transaction', 'object'])


def string_op(op):
    if op.action in ['c', 'a']:
        return '{}{}'.format(op.action, op.transaction)
    else:
        return '{}{}({})'.format(*op)


Op.__repr__ = string_op


def parse(string):
    return [Op(*op) for op in re.findall(r'(a|c|r|w)(\d)(?:\((\w)\))?', string)]

def parse_when_necessary(fun):
    def f(s, *args, **kwargs):
        if isinstance(s, str):
            return fun(parse(s), *args, **kwargs)
        else:
            return fun(s, *args, **kwargs)
    return f


@parse_when_necessary
def aborts(s):
    return [op.transaction for op in s if op.action == 'a']


@parse_when_necessary
def commits(s):
    return [op.transaction for op in s if op.action == 'c']


@parse_when_necessary
def conf(s):
    commited = [t for (x, t, _) in s if x == 'c']
    ops = [Op(x, t, o) for (x, t, o) in s if t in commited and x != 'c']

    confs = []
    for i, op in enumerate(ops):
        x, t, o = op
        conflicts = ['r', 'w'] if x == 'w' else ['w']
        confs += [(op, op2) for op2 in ops[i + 1:] if t != op2.transaction
                  and o == op2.object and op2.action in conflicts]
    return confs


def conf_equivalent(s1, s2):
    raise NotImplementedError()


@parse_when_necessary
def display_confgraph(s):
    import graphviz

    edges = {(op1.transaction, op2.transaction) for op1, op2 in conf(s)}
    nodes = {op.transaction for op in s}

    dot = graphviz.Digraph('Konfliktgraph')
    for node in nodes:
        dot.node(str(node))
    for (t1, t2) in edges:
        dot.edge(str(t1), str(t2))
    dot.render(view=True)


@parse_when_necessary
def reads(s):
    ops = list(reversed(s))
    reads = []
    for i, (x, t, o) in enumerate(ops):
        if x == 'r':
            aborted = aborts(s)
            write_t = next(
                (op.transaction for op in ops[i:]
                 if op.action == 'w' and op.transaction not in aborted
                 and op.transaction != t and op.object == o), None)
            if write_t is not None:
                reads.append((t, o, write_t))
    return list(reversed(reads))


@parse_when_necessary
def rc(s):
    print('----- Checking for RC -----')
    s_reads = reads(s)
    commited = commits(s)
    for ti, x, tj in s_reads:
        print('{} liest {} von {}: '.format(ti, x, tj), end='')
        if ti in commited:
            if tj not in commited[:commited.index(ti)]:
                print('{} wird nicht vor {} commited. NON-RC.'.format(tj, ti))
                return False
            print('{} wird vor {} commited. OK.'.format(tj, ti))
        else:
            print('{} wird nicht commited. OK.'.format(ti))
    print('RC')
    return True


def aca(s):
    print('----- Checking for ACA -----')
    for ti, x, tj in reads(s):
        print('t{} liest {} von t{}: '.format(ti, x, tj), end='')
        index = s.index(Op('r', ti, x))
        if ('c', tj, '') not in s[:index]:
            print('t{} wird nicht vor r{}({}) commited. NON-ACA.'.format(
                tj, ti, x))
            return False
        print('{} wird vor r{}({}) commited. OK.'.format(tj, ti, x))
    print('ACA')
    return True


@parse_when_necessary
def st(s):
    print('----- Checking for ST -----')
    commited = commits(s)
    for i, writeop in enumerate(s):
        (x, t, o) = writeop
        if x == 'w':
            print('Betrachte {}: '.format(writeop), end='')
            op_end = Op('c' if t in commited else 'a', t, '')
            for op in s[i:s.index(op_end)]:
                if op.transaction != t and op.object == o:
                    print('{} < {} aber {} < {}. NON-ST'.format(
                        writeop, op, op, op_end))
                    return False
            print(
                'auf {} wird vor {} von keinen anderen Transaktionen zugegriffen. OK.'
                .format(o, op_end))
    print('ST')
    return True

@parse_when_necessary
def recoverable(s):
    return st(s) or aca(s) or rc(s)

def lockable(op, locked):
    if op.action not in ['r', 'w']:
        return True
    for t, locks in locked.items():
        if t != op.transaction:
            for a, _, o in locks:
                if o == op.object and not (op.action == a == 'r'):
                    return False
    return True

def lock(op):
    a, t, o = op
    return Op(a + 'l', t, o)

def unlock(op):
    a, t, o = op
    return Op(a + 'u', t, o)

@parse_when_necessary
def actions(s, t):
    return [op for op in s if op.transaction == t and op.action in ['r', 'w']]

@parse_when_necessary
def c2pl(s):
    ns = []
    delayed = []
    locked = {}
    remaining = s.copy()
    commits = {op.transaction: op for op in remaining if op.action in ['a', 'c']}
    remaining = [op for op in remaining if op not in commits.values()]
    while remaining:
        op = remaining.pop(0)
        if op.transaction not in locked:
            required = actions(s, op.transaction)
            for r in required:
                if not lockable(r, locked):
                    delayed.append(op)
                    break
            else:
                ns += [lock(r) for r in required]
                locked[op.transaction] = required
                # Push current operation back.
                remaining.insert(0, op)
        else:
            # Required locks have been aquired.
            ns += [op, unlock(op)]
            locked[op.transaction].pop(0)
            if len(locked[op.transaction]) == 0:
                ns += [commits[op.transaction]]
            remaining = delayed + remaining
            delayed = []
    return ns


s = parse(schedule_input)
s2 = parse(
    'r3(y) r3(z) w2(x) r1(y) w1(x) r2(x) r2(z) w1(y) c1 w3(x) c3 w2(y) r3(x) c2'
)

@parse_when_necessary
def s2pl(s, strict=False):
    ns = []
    delayed = []
    locked = defaultdict(list)
    remaining = s.copy()
    while remaining:
        op = remaining.pop(0)
        a, t, o = op
        if actions(delayed, t) or not lockable(op, locked):
            delayed.append(op)
        elif a in ['a', 'c']:
            ns += [unlock(l) for l in locked[t]] + [op]
            locked[t] = []
            remaining = delayed + remaining
            delayed = []
        else:
            ns += [lock(op), op]
            if not strict and a == 'r':
                ns += [unlock(op)]
            else:
                locked[t].append(op)
            remaining = delayed + remaining
            delayed = []
    if delayed:
        return False, ns, delayed
    else:
        return True, ns
