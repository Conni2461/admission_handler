import math
from collections import Counter

class BzantineNode:
    def __init__(self, l, v):
        self.l = l
        self.v = v
        self.children = []

class BzantineTree:
    def __init__(self, n):
        self._n = n
        self._height = math.floor((self._n - 1) / 3) + 1
        self._head = None
        self._len = 0

    def push(self, l, v):
        self._len += 1
        if self._head == None:
            self._head = BzantineNode(l, v)
            return

        current = self._head
        for n in reversed(range(len(l) - 1)):
            for curr_child in current.children:
                if l[n] == curr_child.l[0]:
                    current = curr_child
                    break

        current.children.append(BzantineNode(l, v))

    def is_full(self):
        max = 1
        for i in range(1, self._height):
            max *= (self._n - (i + 1))

        return (self._len - 1) == max

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
