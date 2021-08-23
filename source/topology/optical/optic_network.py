from topology.optical.optic_node import OpticNode
from topology.optical.optic_fiber import OpticFiber
import networkx as nx

class OpticNetwork:
    def __init__(self):
        self.nodes = {}     # Set of OpticNode objects
        self.fibers = {}    # Set of OpticFiber objects

    def register_node(self, node_name):
        self.nodes[node_name] = OpticNode(node_name)

    def get_node_by_name(self, node_name):
        return self.nodes[node_name]

    def register_fiber(self, fiber_name, src: OpticNode, dst: OpticNode,length,lease_flag=False,max_fp=None,lighted_fp=None,spectrum=None,\
        min_bw=None,max_bw=None):
        self.fibers[fiber_name] = OpticFiber(fiber_name, src, dst, length=length, lease_flag=lease_flag, \
            max_fp=max_fp, lighted_fp=lighted_fp, spectrum=spectrum,min_bw=min_bw,max_bw=max_bw)
    
    def generate_non_direction_graph(self, od_pair_map_optic):
        graph = nx.Graph()
        for optic_name in od_pair_map_optic.values():
            optic_inst = self.fibers[optic_name]
            src_name = optic_inst.src.name
            dst_name = optic_inst.dst.name
            graph.add_edge(src_name, dst_name, name=optic_name, length=optic_inst.length)
        
        return graph
