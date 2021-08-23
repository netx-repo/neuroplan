import pdb, time, sys,torch

from rl.plan_env import PlanEnv
from rl.ac import GCNActorCritic
sys.path.insert(0 ,"../spinningup/")
from spinup import vpg_pytorch

class RL(object):
    def __init__(self, topo, graph_encoder="GCN", num_gnn_layer=2, \
            max_n_delta_bw=1, hidden_sizes=(256, 256), \
            epoch_num=1024, max_action=512,steps_per_epoch=1024,\
            delta_bw=100, checker_mode="all", model_path=None):
        
        self.topo = topo
        
        self.graph_encoder = graph_encoder
        self.num_gnn_layer = num_gnn_layer
        self.hidden_sizes = hidden_sizes

        self.epoch_num = epoch_num
        self.max_action = max_action
        self.steps_per_epoch = steps_per_epoch
        self.delta_bw = delta_bw
        self.max_n_delta_bw = max_n_delta_bw

        self.checker_mode = checker_mode
        self.model_path = model_path
        
        log_dir_name_list = [int(time.time()), len(self.topo.ip.links), self.graph_encoder, \
            self.max_n_delta_bw, self.steps_per_epoch, self.delta_bw]
        self.log_dir = '_'.join([str(i) for i in log_dir_name_list])

    def get_env(self):
        self.env = PlanEnv(self.topo, log_dir=self.log_dir, graph_encoder=self.graph_encoder, \
            max_n_delta_bw=self.max_n_delta_bw, max_action=self.max_action, steps_per_epoch=self.steps_per_epoch, delta_bw=self.delta_bw, checker_mode=self.checker_mode)
        return self.env

    def run_training(self):
        logger_kwargs = dict(output_dir="results/{}".format(self.log_dir), exp_name="test")
        ac_kwargs = dict(graph_encoder_hidden=256,hidden_sizes=self.hidden_sizes, num_gnn_layer=self.num_gnn_layer)

        device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
        ac = GCNActorCritic

        vpg_pytorch(self.get_env, enable_mpi=False, non_blocking=False, gamma=1,actor_critic=ac,\
            max_ep_len=self.max_action, seed=8, device=device, \
            model_path=self.model_path, \
            ac_kwargs=ac_kwargs,epochs=self.epoch_num,steps_per_epoch=self.steps_per_epoch,logger_kwargs=logger_kwargs)

        self.env.terminate()