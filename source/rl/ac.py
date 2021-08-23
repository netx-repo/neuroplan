import numpy as np
import scipy.signal, math
from gym.spaces import Box, Discrete

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.distributions.normal import Normal
from torch.distributions.categorical import Categorical
from torch.nn.parameter import Parameter

import pdb, functools


def mlp(sizes, activation, dropout_flag=False, dropout=0.5, output_activation=nn.Identity):
    layers = []
    for j in range(len(sizes)-1):
        act = activation if j < len(sizes)-2 else output_activation
        if dropout_flag:
            layers += [nn.Linear(sizes[j], sizes[j+1]), act(), nn.Dropout(dropout)]
        else:
            layers += [nn.Linear(sizes[j], sizes[j+1]), act()]
    return nn.Sequential(*layers)


class SimpleGCN(nn.Module):
    """
    Simple GCN layer, similar to https://arxiv.org/abs/1609.02907
    """
    def __init__(self, in_features, out_features):
        super(SimpleGCN, self).__init__()
        self.weight = Parameter(torch.FloatTensor(in_features, out_features))
        self.reset_parameters()

    def reset_parameters(self):
        stdv = 1. / math.sqrt(self.weight.size(1))
        self.weight.data.uniform_(-stdv, stdv)

    # adj_adjust is D^(-0.5)*(adj+I)*D^(0.5)
    def forward(self, h_0, adj_adjust):
        support = torch.matmul(h_0, self.weight)
        output = torch.matmul(adj_adjust, support)
        return output

"""
batch: return (batch_size, one-hot vector encoding for the graph)
one sample: return one-hot vector encoding for the graph
"""
class GCN(nn.Module):
    def __init__(self, feature_num, ip_node_num, n_hidden, num_layer):
        super(GCN, self).__init__()
        self.ip_node_num = ip_node_num
        self.feature_num = feature_num

        self.gcn_list = []
        for i in range(num_layer):
            if i == 0:
                self.gcn_list.append(SimpleGCN(feature_num, n_hidden))
            elif i == num_layer-1:
                self.gcn_list.append(SimpleGCN(n_hidden, feature_num))
            else:
                self.gcn_list.append(SimpleGCN(n_hidden, n_hidden))
        print("num of gcn layer:{}".format(len(self.gcn_list)))
        self.gcn_list = nn.ModuleList(self.gcn_list)

    # node_num: n
    # state_node: batch_size*n*feature_num
    # state_adj: batch_size*n*n
    # obs: batch_size*n*(feature_num+n)
    def forward(self, obs):
        # reconstruct state_node and state_adj from flatten_obs
        if (len(obs.size())==3):
            # batch
            adj_adjust, h_0 = torch.split(obs,[self.ip_node_num, self.feature_num],dim=2)
        else:
            adj_adjust, h_0 = torch.split(obs,[self.ip_node_num, self.feature_num],dim=1)

        for gcn in self.gcn_list:
            h_0 = F.relu(gcn(h_0, adj_adjust))

        if (len(h_0.size())==3):
            # batch
            bn_emb = torch.flatten(h_0,1)
        else:
            bn_emb = torch.flatten(h_0)
        return bn_emb

class Actor(nn.Module):

    def _distribution(self, obs):
        raise NotImplementedError

    def _log_prob_from_distribution(self, pi, act):
        raise NotImplementedError

    def forward(self, obs, act=None):
        # Produce action distributions for given observations, and
        # optionally compute the log likelihood of given actions under
        # those distributions.
        pi = self._distribution(obs)
        logp_a = None
        if act is not None:
            logp_a = self._log_prob_from_distribution(pi, act)
        return pi, logp_a


class GCNCategoricalActor(Actor):

    def __init__(self, feature_num, ip_node_num, gcn, hidden_sizes, act_num, activation):
        super().__init__()
        self.GCN = gcn
        self.logits_net = mlp([feature_num*ip_node_num] + list(hidden_sizes) + [act_num], activation)

    # logits is the log probability, log_p = ln(p)
    def _distribution(self, obs):
        obs_emb = self.GCN(obs)
        logits = self.logits_net(obs_emb)
        return Categorical(logits=logits)

    def _get_logits(self, obs):
        obs_emb = self.GCN(obs)
        logits = self.logits_net(obs_emb)
        return logits

    def _log_prob_from_distribution(self, pi, act):
        return pi.log_prob(act)
    
class GCNCritic(nn.Module):

    def __init__(self, feature_num, ip_node_num, gcn, hidden_sizes, activation):
        super().__init__()
        self.GCN = gcn
        self.v_net = mlp([feature_num*ip_node_num] + list(hidden_sizes) + [1], activation)

    def forward(self, obs):
        return torch.squeeze(self.v_net(self.GCN(obs)), -1) # Critical to ensure v has right shape.



class GCNActorCritic(nn.Module):
    def __init__(self, observation_space, action_space, graph_encoder_hidden=256, num_gnn_layer=2, 
                 hidden_sizes=(64,64), activation=nn.ReLU):
        super().__init__()

        ip_node_num = observation_space.shape[0]
        feature_num = observation_space.shape[1] - ip_node_num
        
        act_num = action_space.n
        self.GCN = GCN(feature_num, ip_node_num, graph_encoder_hidden, num_gnn_layer)
        self.pi = GCNCategoricalActor(feature_num, ip_node_num, self.GCN, hidden_sizes, act_num, activation)

        # build value function
        self.v = GCNCritic(feature_num, ip_node_num, self.GCN, hidden_sizes, activation)
        params_num = sum(functools.reduce( lambda a, b: a*b, x.size()) for x in self.parameters())
        print("# of trainable params:{}".format(params_num))

    def step(self, obs, mask):
        with torch.no_grad():
            pi = self.pi._distribution(obs)
            
            pi_logits = self.pi._get_logits(obs)
            pi_logits_delta = torch.zeros(mask.size()).to(mask.device)
            pi_logits_delta[mask == 0] = float("-Inf")
            pi_logits += pi_logits_delta
            pi_mask = Categorical(logits=pi_logits)
            
            a = pi_mask.sample()
            logp_a = self.pi._log_prob_from_distribution(pi, a)

            v = self.v(obs)
        return a.cpu().numpy(), v.cpu().numpy(), logp_a.cpu().numpy()