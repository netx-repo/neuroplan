#from planning.algorithm import PlanAlg
from simulate.traffic_matrix import TrafficMatrix
from topology.ip.router import Router
from topology.ip.link import Link
from topology.optical.optic_node import OpticNode
from topology.optical.optic_fiber import OpticFiber
from topology.topology import Topology

import matplotlib.pyplot as plt
import pdb, time, sys

# pybind11, c++ impl
import gurobi_c

class ILP(object):
    def __init__(self, topo):
        self.topo = topo
        self.cost_opt = None

    def run_ilp(self, subopt_sol=None, delta_bw=100, relax_factor=1, mipgapabs=5e-2):
        ilp_solve_limit = -1

        non_direct_graph, init_cost = self.topo.ip.generate_non_direction_graph(1, subopt_sol, relax_factor)
        fiber_info = {}
        for fiber_name, fiber_inst in self.topo.optic.fibers.items():
            if fiber_inst.lease_flag:
                max_spectrum = 0
                max_capa = fiber_inst.max_bw
            else:
                max_spectrum = fiber_inst.max_fp*fiber_inst.spectrum
                max_capa = 0

            fiber_info[fiber_name] = (fiber_inst.lease_flag, max_capa, max_spectrum)

        failed_links_for_spof_list = self.topo.failed_links_for_spof_list[:-1]
        print("start ilp_solve_c...", flush=True)
        start_time = time.time()
        (cost_opt, delta_capa_sum, opt_sol) = gurobi_c.ilp_solve_c(non_direct_graph, failed_links_for_spof_list, \
            self.topo.tm.data['all'], self.topo.tm.data['no-bronze'], fiber_info, self.topo.l3node_map_stub, self.topo.load_factor, \
            delta_bw, ilp_solve_limit, mipgapabs)
        print("ilp_solve result, running time: {} \nfinal_cost:{}, init_cost:{}, delta_cost:{}, delta_capa:{}".format(
            int(time.time()-start_time), cost_opt+init_cost, init_cost, cost_opt, delta_capa_sum), flush=True)
        
        print("opt_cost:{}".format(cost_opt), flush=True)
        self.cost_opt = cost_opt
        print(dict(sorted(opt_sol.items(), key=lambda item: item[1], reverse=True)), flush=True)
    
    def run_ilp_heuristic(self, subopt_sol=None, delta_bw=1600, relax_factor=1, spof_group_size=10):
        ilp_solve_limit = -1
        mipgapabs = 0.05
        fiber_info = {}
        for fiber_name, fiber_inst in self.topo.optic.fibers.items():
            if fiber_inst.lease_flag:
                max_spectrum = 0
                max_capa = fiber_inst.max_bw
            else:
                max_spectrum = fiber_inst.max_fp*fiber_inst.spectrum
                max_capa = 0

            fiber_info[fiber_name] = (fiber_inst.lease_flag, max_capa, max_spectrum)
        
        failed_links_for_spof_list = self.topo.failed_links_for_spof_list[:-1]

        spof_group = failed_links_for_spof_list[:spof_group_size]
        group_idx = 0
        total_cost = 0
        total_sol = {}
        total_start_time = time.time()
        while len(spof_group) > 0:
            non_direct_graph, init_cost = self.topo.ip.generate_non_direction_graph(1, subopt_sol, relax_factor)
            start_time = time.time()
            (cost_opt, delta_capa_sum, opt_sol) = gurobi_c.ilp_solve_c(non_direct_graph, spof_group, \
                self.topo.tm.data['all'], self.topo.tm.data['no-bronze'], fiber_info, self.topo.l3node_map_stub, \
                self.topo.load_factor, delta_bw, ilp_solve_limit, mipgapabs, 0)
            print("spof_group_idx:{}, opt_slo:{}, running time:{}".format(group_idx, opt_sol, time.time()-start_time))

            for link_idx, step_size in opt_sol.items():
                self.topo.ip.links[self.topo.ip.idx_map_link_name[link_idx]].incr_bw(step_size*delta_bw)
                try:
                    total_sol[link_idx] += step_size
                except:
                    total_sol[link_idx] = step_size
            
            total_cost += cost_opt
            group_idx += 1
            spof_group = failed_links_for_spof_list[spof_group_size*group_idx:spof_group_size*(group_idx+1)]

        print("heuristic total time:{}".format(time.time()-total_start_time))
        print("opt_cost:{}".format(total_cost), flush=True)
        self.cost_opt = total_cost
        print(dict(sorted(total_sol.items(), key=lambda item: item[1], reverse=True)), flush=True)

