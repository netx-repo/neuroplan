from topology.ip.router import Router

class Flow:
    # cos represents the priority (GOLD-ICP, SILVER, BRONZE)
    def __init__(self, name, src:Router, dst:Router, capacity, cos):
        self.name = name
        self.src = src
        self.dst = dst
        self.capacity = capacity
        self.cos = cos
