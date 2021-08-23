from topology.utils.node import Node


class Link:
    
    def __init__(self, name, optic_set: frozenset, src: Node, dst: Node, idx=-1, initial_bw=0, max_bw=None, igp=0, fiber_map_spectrum=None, cost=None):
        self.name = name
        self.optic_set = optic_set
        self.src = src
        self.dst = dst
        self.idx = idx
        self.initial_bw = initial_bw
        self.bandwidth = initial_bw
        self.max_bw = max_bw
        self.igp = igp
        self.fiber_map_spectrum = fiber_map_spectrum
        self.cost = cost


    def incr_bw(self, delta_bw):
        self.bandwidth += delta_bw

    def reset_bw(self):
        self.bandwidth = self.initial_bw
