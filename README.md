## 0. Introduction
This repository contains the source code for our SIGCOMM'21 paper "Network Planning with Deep Reinforcement Learning".
### Notes
The network topologies and the trained models used in the paper are not open-sourced. One can create synthetic topologies according to the problem formulation in the paper or modify the code for their own use case.

## 1. Environment config
### AWS instance configurations
- AMI image: "Deep Learning AMI (Ubuntu 16.04) Version 43.0 - ami-0774e48892bd5f116"
- for First-stage: g4dn.4xlarge; `Threads 16` in `gurobi.env`
- for others (ILP, ILP-heur, Second-stage): m5zn.12xlarge; `Threads 8` in `gurobi.env`

### Step 0: download the git repo
### Step 1: install Linux dependencies
```
sudo apt-get update
sudo apt-get install build-essential libopenmpi-dev libboost-all-dev
```
### Step 2: install Gurobi
```
cd <repo>/
./gurobi.sh
source ~/.bashrc
```
- Install the license here: https://www.gurobi.com/downloads/free-academic-license/
- Make sure your Gurobi solver work: `gurobi_cl /opt/gurobi902/linux64/examples/data/coins.lp`
### Step 3: setup && start conda environment with python3.7.7
If you use the AWS Deep Learning AMI, conda is preinstalled.
```
conda create --name <env> python=3.7.7
conda activate <env>
```
### Step 4: install python dependencies in the conda env
```
cd <repo>/spinninup
pip install -e .
pip install networkx pulp pybind11 xlrd==1.2.0
```
### Step 5: compile C++ program with pybind11
```
cd <repo>/source/c_solver
./compile.sh
```
## 2. Content
- source
    - c_solver: C++ implementation with Gurobi APIs for ILP solver and network plan evaluator
    - planning: `ILP` and `ILP-heur` implementation
    - results: store the provided trained models and solutions, and the training log
    - rl: the implementations of Critic-Actor, RL environment and RL solver 
    - simulate: python classes of flow, spof, and traffic matrix
    - topology: python classes of network topology (both optical layer and IP layer)
    - `test.py`: the main script used to reproduce results
- spinningup
    - adapted from [OpenAI Spinning Up](https://github.com/openai/spinningup)
- `gurobi.sh`
    - used to install Gurobi solver
## 3. Reproduce results (for SIGCOMM'21 artifact evaluation)
### Notes 
- Some data points are time-consuming to get (i.e., First-stage for A-0, A-0.25, A-0.5, A-0.75 in Figure 8 and B, C, D, E in Figure 9). We provide pretrained models in `<repo>/source/results/trained/<topo_name>/`, which will be loaded by default. 
- We recommend distributing different data points and differetnt experiments on multiple AWS instances to run simultaneously.
- The default `epoch_num` for Figure 10, 11 and 12 is set to be 1024, to guarantee the convergence. The training process can be terminated manually if convergence is observed.
### How to reproduce
- `cd <repo>/source`
- Figure 7: `python test.py fig_7 <epoch_num>`, `epoch_num` can be set smaller than 10 (e.g. 2) to get results faster.
- Figure 8: `python test.py single_dp_fig8 <alg> <adjust_factor>` produces one data point at a time (the default adjust_factor is 1).  
    - For example, `python test.py single_dp_fig8 ILP 0.0` runs ILP algorithm for `A-0`. 
    - Pretrained models will be loaded by default if provided in `source/results/trained/`. To train from scratch which is **NOT RECOMMENDED**, run `python test.py single_dp_fig8 <alg> <adjust_factor> False`
- Figure 9&13: `python test.py single_dp_fig9 <topo_name> <alg>` produces one data point at a time. 
    - For example, `python test.py single_dp_fig9 E NeuroPlan` runs NeuroPlan (First-stage) for topology E with the pretrained model. To train from scratch which is **NOT RECOMMENDED**, run `python test.py single_dp_fig9 E NeuroPlan False`. 
    - `python test.py second_stage <topo_name> <sol_path> <relax_factor>` can load the solution from the first stage in `<sol_path>` and run second-stage with `relax_factor=<relax_factor>` on topo `<topo_name>`. For example, `python test.py second_stage D "results/<log_dir>/opt_topo/***.txt" 1.5` 
    - we also provide our results of First-stage in `results/trained/<topo_name>/<topo_name>.txt`, which can be used to run second-stage directly. For example, `python test.py second_stage C "results/trained/C/C.txt" 1.5`
- Figure 10: `python test.py fig_10 <adjust_factor> <num_gnn_layer>`. 
    - `adjust_factor={0.0, 0.5, 1.0}, num_gnn_layer={0, 2, 4}`
    - For example, `python test.py fig_10 0.5 2` runs NeuroPlan with `2`-layer GNNs for topology `A-0.5`
- Figure 11: `python test.py fig_11 <adjust_factor> <mlp_hidden_size>`. 
    - `adjust_factor={0.0, 0.5, 1.0}, mlp_hidden_size={64, 256, 512}`
    - For example, `python test.py fig_11 0.0 512` runs NeuroPlan with hidden_size=`512` for topology `A-0`
- Figure 12: `python test.py fig_12 <adjust_factor> <max_unit_per_step>`. 
    - `adjust_factor={0.0, 0.5, 1.0}, max_unit_per_step={1, 4, 16}`
    - For example, `python test.py fig_11 1.0 4` runs NeuroPlan with max_unit_per_step=`4` for topology `A-1`

## 4. Contact
For any question, please contact `hzhu at jhu dot edu`.
