import networkx as nx

import topology.ip as ip
from topology.ip.router import Router
from topology.ip.link import Link
import collections, pdb, sys
from pulp import *
import numpy as np


class Network:
    def __init__(self):
        self.routers = {}       # Set of Router objects
        self.links = {}         # Set of Link objects

        self.idx_map_router_name = {}
        self.router_name_map_idx = {}
        self.router_idx_cnt = 0

        self.link_name_map_cost = {}
        self.idx_map_link_name = {}
        self.link_name_map_idx = {}
        self.link_name_map_od_pair = {}
        self.link_name_map_fiber_and_spectrum = {}

        # utils for multiple edge between two routers
        self.od_pair_map_dup_cnt = {}

    def reset_link_bw(self):
        for link in self.links.values():
            link.reset_bw()

    def clear_links(self):
        self.links = {}
        self.idx_map_link_name = {}
        self.link_name_map_idx = {}

    def register_router(self, router_name, l1_node, stub):
        self.routers[router_name] = Router(router_name, l1_node, stub)
        self.idx_map_router_name[self.router_idx_cnt] = router_name
        self.router_name_map_idx[router_name] = self.router_idx_cnt
        self.router_idx_cnt += 1

    def get_router_by_name(self, router_name):
        return self.routers[router_name]

    def register_link(self, link_name, optic_set, src, dst, idx=-1, initial_bw=0, max_bw=0, igp=0, fiber_map_spectrum=None, cost=None):
        try:
            assert(link_name not in self.links)
        except:
            raise Exception("exist link_name:{}".format(link_name))

        self.idx_map_link_name[idx] = link_name
        self.link_name_map_idx[link_name] = idx

        self.links[link_name] = Link(link_name, optic_set, src, dst, idx=idx, initial_bw=initial_bw,\
            max_bw=max_bw, igp=igp, fiber_map_spectrum=fiber_map_spectrum,cost=cost)

    def add_link(self, src_router, dst_router, bandwidth):
        src, dst = src_router.name, dst_router.name
        link_name = '%s-%s' % (min(src, dst), max(src, dst))
        new_link = Link(src_router, dst_router, bandwidth)
        self.links[link_name] = new_link

    def generate_graph_from_multi_edge(self, failed_link_name_list=[]):
        graph = nx.DiGraph()
        capa_matrix = {}
        # Add nodes
        for link_name, link in self.links.items():
            src_name = link.src.name
            dst_name = link.dst.name

            if link_name not in failed_link_name_list:
                # parallel edges between two nodes
                try:
                    capa_matrix[(src_name, dst_name)] += link.bandwidth
                except:
                    capa_matrix[(src_name, dst_name)] = link.bandwidth

        # add nodes and edges
        for (src_name, dst_name), bw in capa_matrix.items():
            graph.add_edge(src_name, dst_name, capacity=bw)
            graph.add_edge(dst_name, src_name, capacity=bw)
        return graph

    # generate non direction graph, used to perform a complete ILP approach
    # max_cstr_sol is used to take the second step for RL approach
    def generate_non_direction_graph(self, adjust_factor=1.0, max_cstr_sol=None, relax_factor=1):
        graph = nx.MultiGraph()
        init_cost = 0
        for link_name, link in self.links.items():

            src_name = link.src.name
            dst_name = link.dst.name
            if max_cstr_sol == None:
                max_delta_step = -1
            else:
                max_delta_step = int(max_cstr_sol.get(link.idx, 0)*relax_factor)

            graph.add_edge(src_name, dst_name, capacity=int(link.bandwidth*adjust_factor), name=link_name, cost=link.cost, \
                fiber_map_spectrum=link.fiber_map_spectrum, idx=link.idx, max_delta_step=max_delta_step)   
            init_cost += link.bandwidth*link.cost

        return graph, init_cost

    def generate_graph(self, failed_links=None):
        graph = nx.DiGraph()

        # Add nodes
        graph.add_nodes_from(list(self.routers.keys()))

        # Add edges
        for link in self.links.values():
            if failed_links is None or link not in failed_links:
                # add bidirectional edge
                graph.add_edge(link.src.name, link.dst.name, capacity=link.bandwidth)
                graph.add_edge(link.dst.name, link.src.name, capacity=link.bandwidth)

        return graph
