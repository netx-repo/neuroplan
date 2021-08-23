from topology.optical.optic_node import OpticNode
from topology.optical.optic_fiber import OpticFiber

class OpticPath:
    def __init__(self, node_name_set: set, fiber_name_list: list, length):
        self.node_name_set = node_name_set    
        self.fiber_name_list = fiber_name_list 
        self.length = length