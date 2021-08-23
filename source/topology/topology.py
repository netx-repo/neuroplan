from topology.ip.network import Network
from topology.optical.optic_network import OpticNetwork, OpticFiber
from topology.ip.link import Link
from topology.ip.router import Router
from topology.optical.optic_node import OpticNode
from topology.optical.optic_path import OpticPath

from simulate.traffic_matrix import TrafficMatrix
from simulate.spofs import Spofs
from itertools import islice


import sys, pdb, time, math, json
import os
import collections

import numpy as np
import random as rd
import networkx as nx
import pandas as pd
from pulp import *

# pybind11, c++ impl
import gurobi_c

class Topology:
    '''
        A class for the whole topology, including the optical network, IP network, and the mapping from IP links to optical fibers.
    '''

    # Construction function
    def __init__(self, adjust_factor=1.0):
        self.ip = Network()
        self.optic = OpticNetwork()
        self.tm = TrafficMatrix()

        self.mapping = {}

        self.spofs = Spofs()
        # use spof_list to only store the fiber_name, easy to do checking
        self.spof_list = []
        self.fiber_from_fiber = set()
        self.fiber_from_lease = set()

        # used for handling multiple edges between two nodes
        self.od_pair_map_link_cnt = {}
        self.od_pair_map_link_name = {}

        # used for checking capacity constraints for "Leases"
        self.fiber_map_capacity_sum = {}
        # used for checking spectrum constraints for "Fibers"
        self.fiber_map_spectrum_sum = {}

        # used for cache the visited state
        self.l3_link_idx_map_delta_bw= {}

        # utils for check spof
        self.spof_failed_point = 0

        # store the solution
        self.ip_sol = Network()

        # store the l3node stub, used for c++ check
        self.l3node_map_stub = {}
        self.load_factor = 0.8

        # adjust_factor is used to set different initial capa
        self.adjust_factor = adjust_factor

        # optic info related
        self.od_pair_map_optic_name = {}
        self.od_pair_map_fiber_name = {}
        self.od_pair_map_lease_name = {}
        self.optic_pair_name_set = set()

    # reset the stateful states
    def reset(self):
        self.ip.reset_link_bw()
        self.generate_delta_bw_matrix_from_spof_list()
        self.spof_failed_point = 0
        self.init_cstr_state()

    def init_cstr_state(self):
        # used for storing the delta on the l3 link
        self.l3_link_idx_map_delta_bw= {}

        self.fiber_map_capacity_sum = {}
        self.fiber_map_spectrum_sum = {}

        for link in self.ip.links.values():
            for fiber in link.fiber_map_spectrum:
                if self.optic.fibers[fiber].lease_flag:
                    # fibers in "Leases"
                    try:
                        self.fiber_map_capacity_sum[fiber] += link.initial_bw
                    except:
                        self.fiber_map_capacity_sum[fiber] = link.initial_bw
                else:
                    # fibers in "Fibers", care about spectrum
                    used_spectrum = round(link.initial_bw*link.fiber_map_spectrum[fiber],5)
                    try:
                        self.fiber_map_spectrum_sum[fiber] += used_spectrum
                    except:
                        self.fiber_map_spectrum_sum[fiber] = used_spectrum

    def import_fiber_from_file(self, file_path):
        df = pd.read_excel(file_path, sheet_name="Fibers")
        fiber_node_set = set()
        fiber_name_set = set()

        for index, row in df.iterrows():
            #register node
            self.optic.register_node(row['src'])
            self.optic.register_node(row['dst'])
            self.fiber_from_fiber.add(row['name'])
            # register fiber
            self.optic.register_fiber(row['name'],self.optic.get_node_by_name(row['src']),self.optic.get_node_by_name(row['dst']),\
                length=int(row['rtt']),lease_flag=False,max_fp=int(row['max_fp']),spectrum=int(row['spectrum_size_ghz_per_fp']))

            src_name = min(row['src'], row['dst'])
            dst_name = max(row['src'], row['dst'])

            od_pair = (src_name, dst_name)
            self.optic_pair_name_set.add(od_pair)

            try:
                self.od_pair_map_fiber_name[od_pair].append(row['name'])
            except:
                self.od_pair_map_fiber_name[od_pair] = [row['name']]
            
            try:
                self.od_pair_map_optic_name[od_pair].append(row['name'])
            except:
                self.od_pair_map_optic_name[od_pair] = [row['name']]
            
        print("# of l1 node:{}, # of fibers:{}".format(len(self.optic.nodes), len(self.optic.fibers)))

    def import_lease_from_file(self, file_path):
        df = pd.read_excel(file_path, sheet_name="Leases")

        for index, row in df.iterrows():
            self.optic.register_node(row['src'])
            self.optic.register_node(row['dst'])
            self.fiber_from_lease.add(row['name'])
            self.optic.register_fiber(row['name'],self.optic.get_node_by_name(row['src']),self.optic.get_node_by_name(row['dst']),\
                length=int(row['rtt']),lease_flag=True,min_bw=int(row['min_capacity_gbps']),max_bw=int(row['max_capacity_gbps']))

            src_name = min(row['src'], row['dst'])
            dst_name = max(row['src'], row['dst'])
            
            od_pair = (src_name, dst_name)
            try:
                self.od_pair_map_lease_name[od_pair].append(row['name'])
            except:
                self.od_pair_map_lease_name[od_pair] = [row['name']]
            
            try:
                self.od_pair_map_optic_name[od_pair].append(row['name'])
            except:
                self.od_pair_map_optic_name[od_pair] = [row['name']]
            
            self.optic_pair_name_set.add(od_pair)

        print("# of fibers after importing leases:{}".format(len(self.optic.fibers)))

    def import_l3_node_from_file(self, file_path):
        df = pd.read_excel(file_path, sheet_name="L3Nodes")

        l3_node_set = set()

        for index, row in df.iterrows():
            assert(row["name"]==row["l1_node"])
            assert(row["l1_node"] in self.optic.nodes)
            l3_node_set.add(row["l1_node"])
            self.l3node_map_stub[row["name"]] = row["stub"]
            self.ip.register_router(row["name"], self.optic.get_node_by_name(row["l1_node"]), row["stub"])
        print("# of l3 node:{}".format(len(self.ip.routers)))

    def import_l3_link_from_file(self, file_path, simplified_link=-1):
        df = pd.read_excel(file_path, sheet_name="L3Links")

        self.l3_link_related_node_pairs = set()
        self.l3_link_optics_set = set()

        self.od_pair_map_link_idx_list = {}
        self.candidate_idx = 0

        for index, row in df.iterrows():
            if simplified_link > 0 and self.candidate_idx > simplified_link:
                break

            assert(row['src'] in self.ip.routers)
            assert(row['dst'] in self.ip.routers)

            init_capa = int(int(row['min_capacity_gbps'])*self.adjust_factor)

            item_str_list = row['fiber_name_map_spectrum'].split(";")
            fiber_map_spectrum = {}
            optic_node_pair_set = set()
            for item in item_str_list:
                k, v = item.split(":")
                assert(k in self.optic.fibers)

                # check the solution
                assert(int(row['final_capacity_gbps'])<=int(row['max_capacity_gbps']))
                assert(int(row['final_capacity_gbps'])>=init_capa)

                fiber_map_spectrum[k] = float(v)

                if self.optic.fibers[k].lease_flag:
                    # fibers in "Leases"
                    try:
                        self.fiber_map_capacity_sum[k] += init_capa
                    except:
                        self.fiber_map_capacity_sum[k] = init_capa

                else:
                    # fibers in "Fibers", care about spectrum
                    used_spectrum = round(init_capa*fiber_map_spectrum[k],5)
                    try:
                        self.fiber_map_spectrum_sum[k] += used_spectrum
                    except:
                        self.fiber_map_spectrum_sum[k] = used_spectrum
                
                # store the optic path
                optic_src_name = self.optic.fibers[k].src.name
                optic_dst_name = self.optic.fibers[k].dst.name
                optic_pair = (min(optic_src_name, optic_dst_name), max(optic_src_name, optic_dst_name))
                optic_node_pair_set.add(optic_pair)

            # set the cost of link: sum of the length of the fiber
            l3_link_cost = sum([self.optic.fibers[fiber].length for fiber in fiber_map_spectrum])

            src_name = min(row['src'], row['dst'])
            dst_name = max(row['src'], row['dst'])
            od_pair = (src_name, dst_name)
            self.l3_link_related_node_pairs.add(od_pair)
            try:
                self.od_pair_map_link_idx_list[od_pair].append(self.candidate_idx)
            except:
                self.od_pair_map_link_idx_list[od_pair] = [self.candidate_idx]
            try:
                self.od_pair_map_link_name[od_pair].append(row['name'])
            except:
                self.od_pair_map_link_name[od_pair] = [row['name']]

            optic_set = frozenset(fiber_map_spectrum.keys())
            assert(optic_set not in optic_set)
            self.l3_link_optics_set.add(optic_set)

            self.ip.register_link(row['name'], optic_set, self.ip.get_router_by_name(src_name), self.ip.get_router_by_name(dst_name),\
                idx=self.candidate_idx, initial_bw=init_capa, max_bw=int(row['max_capacity_gbps']),\
                igp=int(row['igp']), fiber_map_spectrum=fiber_map_spectrum, cost=l3_link_cost)
            self.candidate_idx += 1

            
        print("# of l3 links in excel:{}".format(len(self.ip.links)))

        # check the initial ip capacity satisfy the constraints
        for fiber_name, capa_sum in self.fiber_map_capacity_sum.items():
            assert(capa_sum<=self.optic.fibers[fiber_name].max_bw)
            
        for fiber_name, spectrum_sum in self.fiber_map_spectrum_sum.items():
            assert(spectrum_sum<=self.optic.fibers[fiber_name].max_fp * self.optic.fibers[fiber_name].spectrum)

        # calculate the cost of init state
        cost, capa = 0, 0
        for link_name, link_inst in self.ip.links.items():
            cost += link_inst.initial_bw * link_inst.cost
            capa += link_inst.initial_bw
        
        print("init state cost:{}, capa:{}".format(cost, capa))
        
    def check_spofs_for_init_state(self, simplified_spof=-1):
        if simplified_spof == 0:
            spof_list = [[]]
        elif simplified_spof == -1:
            spof_list = self.spof_list
        else:
            spof_list = self.spof_list[:simplified_spof]

        delta_bw_matrix_list = []
        for idx, spof in enumerate(spof_list):
            delta_bw_matrix = collections.defaultdict(dict)
            for link_name in self.spof_idx_map_failed_link_name_list[idx]:
                link = self.ip.links[link_name]
                # failed_link
                try:
                    delta_bw_matrix[link.src.name][link.dst.name] += link.bandwidth
                except:
                    delta_bw_matrix[link.src.name][link.dst.name] = link.bandwidth

            delta_bw_matrix_list.append(delta_bw_matrix)

        complete_graph = self.ip.generate_graph_from_multi_edge([])

        (sat_flag0, opt_cnt0) = gurobi_c.check_sf(complete_graph, delta_bw_matrix_list[:-1], self.tm.data['no-bronze'], self.l3node_map_stub, self.load_factor)
        start_time = time.time()
        (sat_flag1, opt_cnt1) = gurobi_c.check_sf(complete_graph, delta_bw_matrix_list[-1:], self.tm.data['all'], self.l3node_map_stub, self.load_factor)
        print("check init states steady state num:{}, time:{}".format(opt_cnt1, time.time()-start_time))
        if sat_flag0 and sat_flag1:
            sat_flag = True
        else:
            sat_flag = False
        print("init state spof checking: sat_flag:{}, opt_cnt0:{}, opt_cnt1:{}".format(sat_flag,opt_cnt0, opt_cnt1))

    def check_sol_from_dict_file(self, file_path):
        self.init_cstr_state()
        print(file_path)
        sol_dict = json.load(open(file_path))
        cost = 0
        for link_name, capa in sol_dict.items():
            self.ip.links[link_name].bandwidth = capa
            delta_bw = capa - self.ip.links[link_name].initial_bw 
            self.update_cstr_state(self.ip.links[link_name], delta_bw)
            cost += delta_bw*self.ip.links[link_name].cost
        
        print("the cost of sol:{}".format(cost))
                
        print("check fiber constraints...")
        self.check_cstr_state()
        spof_list = self.spof_list
        delta_bw_matrix_list = []
        for idx, spof in enumerate(spof_list):
            delta_bw_matrix = collections.defaultdict(dict)
            for link_name in self.spof_idx_map_failed_link_name_list[idx]:
                link = self.ip.links[link_name]
                # failed_link
                try:
                    delta_bw_matrix[link.src.name][link.dst.name] += link.bandwidth
                except:
                    delta_bw_matrix[link.src.name][link.dst.name] = link.bandwidth
            delta_bw_matrix_list.append(delta_bw_matrix)

        print("check spofs...")
        complete_graph = self.ip.generate_graph_from_multi_edge([])
        start_time = time.time()
        (sat_flag0, opt_cnt0) = gurobi_c.check_sf(complete_graph, delta_bw_matrix_list[:-1], self.tm.data['no-bronze'],self.l3node_map_stub, self.load_factor)
        print("check sol spofs num:{}, time:{}".format(opt_cnt0, time.time()-start_time))
        start_time = time.time()
        (sat_flag1, opt_cnt1) = gurobi_c.check_sf(complete_graph, delta_bw_matrix_list[-1:], self.tm.data['all'],self.l3node_map_stub, self.load_factor)
        print("check sol steady state num:{}, time:{}".format(opt_cnt1, time.time()-start_time))
        if sat_flag0 and sat_flag1:
            sat_flag = True
        else:
            sat_flag = False
        print("sol spof checking: sat_flag:{}, sat_flag0:{}, sat_flag1:{}, opt_cnt0:{}, opt_cnt1:{}".format(\
            sat_flag, sat_flag0, sat_flag1, opt_cnt0, opt_cnt1))

    def import_tm_from_file(self, file_path, simplified_tm=-1):
        rd.seed(1)

        df = pd.read_excel(file_path, sheet_name="Flows")
        flow_identifier = set()

        flow_od_pairs = set()
        self.tm_nodes = set()
        for index, row in df.iterrows():

            if simplified_tm > 0 and index > simplified_tm:
                break
            assert(row['src'] in self.ip.routers)
            assert(row['dst'] in self.ip.routers)
            assert((row['src'], row['dst'], row['cos']) not in flow_identifier)

            flow_identifier.add((row['src'], row['dst'], row['cos']))
            adjust_flow_size = math.ceil(float(row['capacity_gbps']))
            
            self.tm.register_flow(row['name'], self.ip.get_router_by_name(row['src']), self.ip.get_router_by_name(row['dst']), \
                adjust_flow_size, row['cos'])
            
            od_pair = (min(row['src'], row['dst']), max(row['src'], row['dst']))
            flow_od_pairs.add(od_pair)
            self.tm_nodes.add(row['src'])
            self.tm_nodes.add(row['dst'])
            
        print("# of flows:{}".format(len(self.tm.flows)))

    def import_spof_from_file(self, file_path, simplified_spof=-1):
        df = pd.read_excel(file_path, sheet_name="Spofs")

        for index, row in df.iterrows():
            if simplified_spof > 0 and index > simplified_spof:
                break
            fiber_name_list = row["fiber_names"].split(";")
            cos_protect_list = row["cos_to_protect"].split(";")
            spof_name = "spof_" + str(index)
            self.spofs.register_spof(spof_name, fiber_name_list, cos_protect_list)
            self.spof_list.append(fiber_name_list)

        print("# of spofs:{}".format(len(self.spof_list)))

        self.add_single_fiber_failure_and_no_failure()
        print("# of spofs:{} after add single fiber failure and no failure state".format(len(self.spof_list)))

    def add_single_fiber_failure_and_no_failure(self):
        for fiber_name in self.optic.fibers:
            if self.optic.fibers[fiber_name].lease_flag == False:
                self.spof_list.append([fiber_name])

        self.spof_list.append([])

    def gen_failed_ip_link_and_spof_map(self):

        self.spof_idx_map_failed_link_name_list = {}
        self.failed_links_for_spof_list = []
        self.link_name_map_spof_idx_list = {}

        for idx, spof in enumerate(self.spof_list):
            failed_link_name_list = []
            for link_name, link in self.ip.links.items():
                # check if there are common fiber
                if set(spof)&set(link.fiber_map_spectrum.keys()):
                    failed_link_name_list.append(link_name)
                    try:
                        self.link_name_map_spof_idx_list[link_name].append(idx)
                    except:
                        self.link_name_map_spof_idx_list[link_name] = [idx]

            self.spof_idx_map_failed_link_name_list[idx] = failed_link_name_list
            self.failed_links_for_spof_list.append(failed_link_name_list)

    def generate_delta_bw_matrix_from_spof_list(self, simplified_spof=-1):
        if simplified_spof == 0:
            spof_list = [[]]
        elif simplified_spof == -1:
            spof_list = self.spof_list
        else:
            spof_list = self.spof_list[:simplified_spof]

        self.delta_bw_matrix_list = []

        for idx, spof in enumerate(spof_list):
            visited_pair = set()
            delta_bw_matrix = collections.defaultdict(dict)
            for link_name in self.spof_idx_map_failed_link_name_list[idx]:
                link = self.ip.links[link_name]
                src_dst_pair = (link.src.name, link.dst.name)
                dst_src_pair = (link.dst.name, link.src.name)
                assert(dst_src_pair not in visited_pair)
                visited_pair.add(src_dst_pair)
                # failed_link
                try:
                    delta_bw_matrix[link.src.name][link.dst.name] += link.bandwidth
                except:
                    delta_bw_matrix[link.src.name][link.dst.name] = link.bandwidth
            self.delta_bw_matrix_list.append(delta_bw_matrix)

    def update_delta_bw_matrix_list(self, ip_link_idx, delta_bw):
        link_name = self.ip.idx_map_link_name[ip_link_idx]
        link = self.ip.links[link_name]
        spof_idx_list = self.link_name_map_spof_idx_list.get(link_name, [])
        for idx in spof_idx_list:

            self.delta_bw_matrix_list[idx][link.src.name][link.dst.name] += delta_bw

    # checker_mode="vanilla", nothing
    # checker_mode="sa", SA
    # checker_mode="all", stateful checking + SA
    def check_spof(self, added_ip_link_idx, delta_bw, state_map_failed_point_cache, cache_max, checker_mode):
        complete_graph = self.ip.generate_graph_from_multi_edge([])

        self.update_delta_bw_matrix_list(added_ip_link_idx, delta_bw)
        
        state = self.cvt_delta_bw_map()
        if state in state_map_failed_point_cache:
            (sat_flag, spof_fp) = state_map_failed_point_cache[state]
            self.spof_failed_point = spof_fp
            cache_hit_flag = True
        else:
            if checker_mode != "all":
                self.spof_failed_point = 0

            if checker_mode == "vanilla":
                # flow formulation
                (sat_flag, opt_cnt) = gurobi_c.check(complete_graph, self.delta_bw_matrix_list[self.spof_failed_point:-1], \
                    self.tm.data['no-bronze'],self.l3node_map_stub, self.load_factor)
            else:
                # source aggregation
                (sat_flag, opt_cnt) = gurobi_c.check_sf(complete_graph, self.delta_bw_matrix_list[self.spof_failed_point:-1], \
                    self.tm.data['no-bronze'],self.l3node_map_stub, self.load_factor)
            self.spof_failed_point += (opt_cnt-1)
            cache_hit_flag = False
            if len(state_map_failed_point_cache) < cache_max:
                state_map_failed_point_cache[state] = (sat_flag, self.spof_failed_point)
        
        
        if sat_flag == False:
            return sat_flag, cache_hit_flag, state_map_failed_point_cache
        
        if checker_mode == "vanilla":
            # flow formulation
            (sat_flag, opt_cnt) = gurobi_c.check(complete_graph, self.delta_bw_matrix_list[-1:], self.tm.data['all'], \
                self.l3node_map_stub, self.load_factor)
        else:
            # source aggregation
            (sat_flag, opt_cnt) = gurobi_c.check_sf(complete_graph, self.delta_bw_matrix_list[-1:], self.tm.data['all'], \
                self.l3node_map_stub, self.load_factor)
        return sat_flag, cache_hit_flag, state_map_failed_point_cache
    
    # to satisfy the maximal spectrum and capacity constraints of fibers, set mask.
    # =0 means infeasible action; =1 means feasible action
    # [link0_with_1*delta_bw, link0_with_2*delta_bw,..., link0_with_max_delta_bw, link1_with_1*delta_bw,...]
    def get_feasible_action(self, max_n, delta_bw):
        mask_list = [0] * len(self.ip.idx_map_link_name)*max_n
        for link_idx, link_name in self.ip.idx_map_link_name.items():
            link_inst = self.ip.links[link_name]
            for i in range(1, max_n+1):
                sat_flag = self.check_max_cstr(link_inst, delta_bw*i)
                if sat_flag:
                    mask_list[link_idx*max_n+i-1] = 1
        return mask_list

    def aug_l3_link_by_idx_nocheck_max(self, link_idx, delta_bw):

        link_name = self.ip.idx_map_link_name[link_idx]
        link_inst = self.ip.links[link_name]
        self.update_cstr_state(link_inst, delta_bw)
        link_inst.incr_bw(delta_bw)
        return delta_bw*link_inst.cost

    def check_max_cstr(self, link_inst, delta_bw):
        # check the l3_link max_capacity
        if link_inst.bandwidth+delta_bw > link_inst.max_bw:
            return False

        for fiber_name, spectrum_eff in link_inst.fiber_map_spectrum.items():
            fiber_inst = self.optic.fibers[fiber_name]
            if fiber_inst.lease_flag:
                # check the max_capacity in Leases
                if fiber_name not in self.fiber_map_capacity_sum:
                    self.fiber_map_capacity_sum[fiber_name] = 0
                if self.fiber_map_capacity_sum[fiber_name] + delta_bw > fiber_inst.max_bw:
                    return False
            else:
                # check the spectrum in Fibers
                used_spectrum = round(delta_bw*spectrum_eff, 5)
                if fiber_name not in self.fiber_map_spectrum_sum:
                    self.fiber_map_spectrum_sum[fiber_name] = 0
                if self.fiber_map_spectrum_sum[fiber_name] + used_spectrum > fiber_inst.max_fp * fiber_inst.spectrum:
                    return False
        return True

    def check_cstr_state(self):
        sat_flag = True
        # check the max spectrum in Fibers
        for fiber_name, spectrum_sum in self.fiber_map_spectrum_sum.items():
            fiber_inst = self.optic.fibers[fiber_name]
            if spectrum_sum > fiber_inst.max_fp * fiber_inst.spectrum:
                sat_flag = False
                print("{} violate max spectrum, used spectrum:{}, max_spectrum:{}".\
                    format(fiber_name, spectrum_sum, fiber_inst.max_fp * fiber_inst.spectrum))
        
        # check the max and min capa in Leases
        for fiber_name, capa_sum in self.fiber_map_capacity_sum.items():
            fiber_inst = self.optic.fibers[fiber_name]
            if capa_sum > fiber_inst.max_bw:
                sat_flag = False
                print("{} violate max capa, used capa:{}, max_capa:{}".\
                    format(fiber_name, capa_sum, fiber_inst.max_bw))
        
        if sat_flag:
            print("topo satisfy all the max capa constraints")
        return sat_flag

    def update_cstr_state(self, link_inst, delta_bw):
        try:
            self.l3_link_idx_map_delta_bw[link_inst.idx] += delta_bw
        except:
            self.l3_link_idx_map_delta_bw[link_inst.idx] = delta_bw

        for fiber_name, spectrum_eff in link_inst.fiber_map_spectrum.items():
            fiber_inst = self.optic.fibers[fiber_name]
            if fiber_inst.lease_flag:
                 self.fiber_map_capacity_sum[fiber_name] += delta_bw
            else:
                used_spectrum = round(delta_bw*spectrum_eff, 5)
                self.fiber_map_spectrum_sum[fiber_name] += used_spectrum

    def cvt_delta_bw_map(self):
        item_list = [(k, v) for k, v in self.l3_link_idx_map_delta_bw.items()]
        return frozenset(item_list)

    """
    swap node and edge related
    """
    """
    regard "link" as "node", "node" as "edge";
    if two links have one common end, then they are adjacent; otherwise, not.
    Thus, note parallel edges are not adjacent
    """
    def get_edge2node_adj(self):
        np_array = np.full(([len(self.ip.links), len(self.ip.links)]),0)
        for i in range(len(self.ip.links)):
            for j in range(i+1, len(self.ip.links)):
                link1 = self.ip.links[self.ip.idx_map_link_name[i]]
                link2 = self.ip.links[self.ip.idx_map_link_name[j]]
                assert(link1.src.name < link1.dst.name)
                assert(link2.src.name < link2.dst.name)
                if link1.src.name == link2.dst.name or link1.dst.name == link2.src.name:
                    np_array[i][j] = 1
                    np_array[j][i] = 1
        self.edge2node_adj = np_array
    
    def get_edge_feature(self):
        np_array = np.full(([len(self.ip.links),1]),0.0)
        for link_idx in range(len(self.ip.links)):
            np_array[link_idx][0] = self.ip.links[self.ip.idx_map_link_name[link_idx]].bandwidth
        
        np_array = (np_array -np.mean(np_array))/(np.std(np_array)+np.finfo(np.float32).eps)

        return np_array
