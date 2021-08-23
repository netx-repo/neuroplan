import gym
from topology.topology import Topology
from copy import deepcopy
import numpy as np
import pdb, os, time, json
import networkx as nx
import matplotlib.pyplot as plt
import sys, math

class PlanEnv(gym.Env):
    def __init__(self, topo: Topology, log_dir, graph_encoder, max_n_delta_bw, max_action=512,\
            steps_per_epoch=2048, delta_bw=100, checker_mode="all"):
        self.max_action = max_action
        self.steps_per_epoch = steps_per_epoch
        self.checker_mode = checker_mode
        self.delta_bw = delta_bw
        self.max_rwd = None
        self.opt_target = None
        self.action_cnt = 0
        
        self.w1 = 2
        self.w2 = 2
        self.norm_param=1e-7
        self.graph_encoder = graph_encoder
        self.max_n_delta_bw = max_n_delta_bw
        self.max_ip_node = len(topo.ip.routers)

        # related to utils
        self.topo = topo
        self.topo_preprocess()
        self.original_topo = deepcopy(topo)

        obs, _ = self.get_observation()

        self.observation_space = gym.Space(shape=list(obs.shape))
        print("obv_space size: {}".format(self.observation_space.shape))

        self.action_space = gym.spaces.Discrete(len(self.topo.ip.links)*max_n_delta_bw)
        print("act_space size: {}".format(self.action_space.n))
        
        self.cum_rwd = 0
        self.complete_cnt = 0

        self.max_rwd = None
        self.opt_target = None
        self.cost = 0
        self.optm_topo = self.topo
        self.optm_ob = None
        self.opt_action_list = []
        self.optm_epoch_idx = 0
        self.action_list = []
        self.epoch_idx = 0

        self.start_sec_ts = int(time.time())

        action_path = "results/{}/actions.txt".format(log_dir)
        self.topo_path = "results/{}/opt_topo".format(log_dir)
        if not os.path.exists(self.topo_path):
            os.makedirs(self.topo_path)

        self.action_fpr = open(action_path,"w")

        self.action_cnt_cum = 0 # to record the epoch num
        self.traj_set = set() # traj set stores the vars (the set of l3 link candidates) that decide the ilp 
        self.main_epoch_traj_stats_list= []
        traj_path = "results/{}/traj.txt".format(log_dir)
        self.traj_fpr = open(traj_path,"w")
        
        self.main_epoch_traj_num = 0
        self.main_epoch_traj_num_visited = 0
        self.main_epoch_cache_hit_num = 0

        # cache for accelerating check_sf
        # each state is represented as a frozenset((l3_link_idx1, delta_bw), (l3_link_idx2, delta_bw),...)
        self.state_map_fp_cache = {}
        self.cache_max_entry = 1e6
        self.cache_path = "results/{}/cache".format(log_dir)
        if not os.path.exists(self.cache_path):
            os.makedirs(self.cache_path)

    def topo_preprocess(self):
        self.topo.get_edge2node_adj()

    def step(self, action):
        obs, reward, done, info = None, None, False, None

        violate_max_cstr_flag, visited_flag, cache_hit_flag = False, False, False
        adapt_tm = -1

        action_int, act_type = int(action), 0

        l3_link_idx = int(action_int/self.max_n_delta_bw)
        delta_bw_act = self.delta_bw*(int(action_int%self.max_n_delta_bw)+1)
        
        if act_type == 0:
            # add IP link capacity
            cost = self.topo.aug_l3_link_by_idx_nocheck_max(l3_link_idx, delta_bw=delta_bw_act)
            assert(cost >= 0)
        else:
            # remove IP link capacity
            cost = self.topo.aug_l3_link_by_idx_nocheck_max(l3_link_idx, delta_bw=-delta_bw_act)

        self.action_list.append((action_int, self.topo.spof_failed_point))
        self.action_cnt += 1
        self.action_cnt_cum += 1
        obs, mask = self.get_observation()
        
        if cost >= 0:
            # check the spof constraints further
            sat_flag, cache_hit_flag, self.state_map_fp_cache = self.topo.check_spof(l3_link_idx, delta_bw_act, self.state_map_fp_cache, self.cache_max_entry, self.checker_mode)
            reward = -round(cost*self.norm_param, 10)
            self.cost += cost
        else:
            # cost < 0 means violating the max_cstrs
            sat_flag = False
            violate_max_cstr_flag = True
            reward = -400
            

        if sum(mask)==0:
            # no feasible action
            violate_max_cstr_flag = True

        if cache_hit_flag:
            self.main_epoch_cache_hit_num += 1

        if sat_flag or self.action_cnt >= self.max_action or violate_max_cstr_flag:
            done = 1
        else:
            done = 0
        
        if done or (self.action_cnt_cum%self.steps_per_epoch == 0):
            visited_flag = self.is_visited_sol()
        
        if done == 1:
            if sat_flag:
                reward += 0
            else:
                reward -= 1

        self.cum_rwd += reward

        action_idx_map_extra_rwd = None
        self.opt_sol_on_rl = -1
        if sat_flag:
            self.save_if_best()

        if done or (self.action_cnt_cum%self.steps_per_epoch == 0):
            # save trajectory and plan results
            self.save_trajectory(visited_flag, adapt_tm, self.cost, self.cum_rwd, violate_max_cstr_flag, sat_flag)
        info = {"log_ptr": self.traj_fpr, "extra_rwd": action_idx_map_extra_rwd}
        return obs, mask, reward, done, info

    def reset(self):
        self.action_cnt = 0
        self.cum_rwd = 0
        self.cost = 0
        
        self.topo.reset()
        self.epoch_idx += 1
        self.action_list = []
        sys.stdout.flush()

        return self.get_observation()

    def get_observation(self):
        """
        ob['ip_adj']:n*n --- E
        ob['ip_node']:n*d_n ---- F (longitute, latitude, in_traffic, out_traffic)
        """
        E_origin = self.topo.edge2node_adj
        E_hat = E_origin + np.eye(E_origin.shape[0])

        D = np.diag(np.sum(E_hat, axis=1))

        # https://towardsdatascience.com/how-to-do-deep-learning-on-graphs-with-graph-convolutional-networks-62acf5b143d0
        D_spectral = np.sqrt(np.linalg.inv(D))
        E = np.matmul(np.matmul(D_spectral, E_hat),D_spectral)
        
        F = self.topo.get_edge_feature()
        ob = np.concatenate((E,F), axis=1)
        
        mask = np.asarray(self.topo.get_feasible_action(self.max_n_delta_bw,self.delta_bw))
        return ob, mask

    def terminate(self):
        self.action_fpr.write("epoch_cnt:{}, ip_node_num:{}\n".format(self.epoch_idx, self.max_ip_node))
        self.action_fpr.write("total_time(sec):{}\n".format(int(time.time())-self.start_sec_ts))
        self.action_fpr.close()

    def ilp_opt_on_rl(self, action_list):
        l3_link_idx_map_cnt = {}
        for (l3_link_idx,_) in action_list:
            try:
                l3_link_idx_map_cnt[l3_link_idx] += 1
            except:
                l3_link_idx_map_cnt[l3_link_idx] = 1
        
        return self.original_topo.ilp_solve(self.delta_bw, l3_link_idx_map_cnt, relax_factor=1)

    def save_if_best(self):
        self.complete_cnt += 1
            
        if self.opt_target == None or self.opt_target >= self.cost:
            self.max_rwd = self.cum_rwd
            self.opt_target = self.cost
            self.optm_topo = self.topo
            self.optm_ob = self.get_observation()
            self.optm_epoch_idx = self.epoch_idx
            self.opt_action_list = self.action_list[:]
            self.ip_idx_map_num_step = {}
            for i in self.opt_action_list:
                link_idx = int(i[0]/self.max_n_delta_bw)
                delta_bw_act = int(i[0]%self.max_n_delta_bw)+1
                try:
                    self.ip_idx_map_num_step[link_idx] += delta_bw_act
                except:
                    self.ip_idx_map_num_step[link_idx] = delta_bw_act

            main_epoch_idx = int((self.action_cnt_cum-1)/self.steps_per_epoch)
            self.action_fpr.write("local_opt:{} {} {} ilp_opt_ob_rl:{} {} {}\nip_idx_list:{}\n".format(self.epoch_idx, self.max_rwd, self.opt_target, self.opt_sol_on_rl, \
                len(self.opt_action_list), self.opt_action_list, self.ip_idx_map_num_step))
            self.action_fpr.flush()
            
            opt_topo_path = '{}/{}_main_epoch{}_cost{}.txt'.format(self.topo_path, int(time.time())-self.start_sec_ts, main_epoch_idx, self.cost)
            opt_topo_fpr = open(opt_topo_path,"w")
            opt_topo_fpr.write(json.dumps(self.ip_idx_map_num_step))
            opt_topo_fpr.close()
    
    def is_visited_sol(self):
        link_cand_list = [int(action) for (action, cost) in self.action_list]
        link_cand_tuple = tuple(sorted(link_cand_list))
        visited_flag = (tuple(link_cand_tuple) in self.traj_set)
        if visited_flag:
            self.main_epoch_traj_num_visited += 1
        self.main_epoch_traj_num += 1
        self.traj_set.add(link_cand_tuple)

        return visited_flag

    def save_trajectory(self, visited_flag, adapt_tm, cost, reward, violate_max_cstr_flag, sat_flag):
        main_epoch_idx = int((self.action_cnt_cum-1)/self.steps_per_epoch)

        self.traj_fpr.write("main epoch idx:{}, visited_flag:{}, adapt_tm:{}, cost:{}, rwd:{}, violate_max_cstr_flag:{}, sat_flag:{}\n action_list:{} {}\n ".\
            format(main_epoch_idx, visited_flag, adapt_tm, cost, reward, violate_max_cstr_flag, sat_flag, len(self.action_list), self.action_list))
        if self.action_cnt_cum%self.max_action == 0:
            # current epoch terminate
            self.traj_fpr.write("main epoch idx:{}, # of traj:{}, # of visited traj:{}, visited_ratio:{}, cache_hit_num:{}, cache_num:{}\n".
                format(main_epoch_idx, self.main_epoch_traj_num, self.main_epoch_traj_num_visited, \
                round(self.main_epoch_traj_num_visited/self.main_epoch_traj_num, 4), self.main_epoch_cache_hit_num, len(self.state_map_fp_cache)))
            self.main_epoch_traj_num_visited = 0
            self.main_epoch_traj_num = 0 
            self.main_epoch_cache_hit_num = 0
            
        self.traj_fpr.flush()
