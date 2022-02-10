import math
from collections import Counter
from enum import Enum


class ByzantineNode:
    def __init__(self, l, v):
        self.l = l
        self.v = v
        self.children = []


class ByzantineTree:
    def __init__(self, n):
        self._n = n
        self._height = math.floor((self._n - 1) / 3) + 1
        self._head = None
        self._len = 0

        prev = 1
        self._max = 1
        for i in range(1, self._height):
            prev = prev * (n - 1 - i)
            self._max += prev

    def push(self, l, v):
        self._len += 1
        if self._head == None:
            self._head = ByzantineNode(l, v)
            return

        current = self._head
        for n in reversed(range(len(l) - 1)):
            for curr_child in current.children:
                if l[n] == curr_child.l[0]:
                    current = curr_child
                    break

        current.children.append(ByzantineNode(l, v))

    def is_full(self):
        return self._len == self._max

    def _find_mc_for_level(self, node, level):
        if level == 0:
            return node.v
        elif level > 0:
            c = Counter()
            c[node.v] += 1
            for child in node.children:
                c[self._find_mc_for_level(child, level - 1)] += 1

            mc = c.most_common()
            return mc[0][0]

    def complete(self):
        c = Counter()
        for i in reversed(range(0, self._height)):
            c[self._find_mc_for_level(self._head, i)] += 1

        mc = c.most_common()
        return mc[0][0]


class ByzantineLeaderCache:
    def __init__(self, id):
        self.id = id
        self.results = []
        self.counter = Counter()


class ByzantineMemberCache:
    def __init__(self, id, n):
        self.id = id
        self.tree = ByzantineTree(n)


class ByzantineStates(Enum):
    STARTED = 0
    FINISHED = 1
    ABORTED = 2
