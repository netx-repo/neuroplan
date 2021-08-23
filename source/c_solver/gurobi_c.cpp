#include <pybind11/pybind11.h>
#include <iostream>
#include <fstream>
#include <algorithm>
#include <unordered_map>
#include <vector>
#include <string>
#include "gurobi_c++.h"
#include <pybind11/stl.h>
#include <ctime>
#include <tuple>
#include <chrono>
#include <boost/functional/hash.hpp>

namespace py = pybind11;
using namespace pybind11::literals;
using namespace std::chrono; 

// source aggregation formulation (SF)
std::tuple<bool, int> check_sf(py::object graph, py::list failures, py::dict traffic_mattrix, py::dict node_stub, py::float_ load_factor){
    // Create an environment
    GRBEnv env = GRBEnv();

    // Create an empty model
    GRBModel model = GRBModel(env);
    int opt_cnt  = 0;
    py::object g = py::module::import("networkx").attr("DiGraph");
    g = graph;
    std::unordered_map<std::string, double> node_srctraffic;
    std::unordered_map<std::string, double> node_dsttraffic;
    std::unordered_map<std::string, std::vector<GRBVar>> node_intraffic_map_vars;
    std::unordered_map<std::string, std::vector<GRBVar>> node_outtraffic_map_vars;
    std::unordered_map<std::string, std::vector<GRBLinExpr>> link_map_vars;

    std::unordered_map<std::string, std::pair<double, GRBLinExpr>> original_link_capacity;
    std::unordered_map<std::string, bool> l3node_map_stub;
    std::vector<GRBConstr> capacity_constr;

    for (auto item : node_stub) {
        l3node_map_stub[std::string(py::str(item.first))] = item.second.cast<bool>();
    };

    for(auto & src : traffic_mattrix){
        std::string flow_src = std::string(py::str(src.first));
        float src_agg_flow_size = 0;
        node_dsttraffic.clear();
        node_intraffic_map_vars.clear();
        node_outtraffic_map_vars.clear();

        for(auto dst: py::dict(py::reinterpret_borrow<py::object>(src.second))){
            src_agg_flow_size += stod(std::string(py::str(dst.second)));
            node_dsttraffic[std::string(py::str(dst.first))] = stod(std::string(py::str(dst.second)));
        }
        for(auto & edge_it: py::list(g.attr("edges"))){
            py::tuple edge = py::tuple(py::reinterpret_borrow<py::object>(edge_it));
            std::string src_str = std::string(py::str(edge[0]));
            std::string dst_str = std::string(py::str(edge[1]));
            std::string link_name = src_str + "_" + dst_str;
            std::string var_name = flow_src + "flow_src" + link_name;

            GRBVar lp_var = model.addVar(0.0, GRB_INFINITY, 0.0, GRB_CONTINUOUS, var_name);
            node_outtraffic_map_vars[src_str].push_back(lp_var);
            node_intraffic_map_vars[dst_str].push_back(lp_var);
            link_map_vars[link_name].push_back(lp_var);
        }
        for(auto & node: py::list(g.attr("nodes"))){
            std::string node_str = std::string(py::str(node));
            GRBLinExpr intraffic_sum = 0;
            GRBLinExpr outtraffic_sum = 0;
            for(auto & var: node_intraffic_map_vars[node_str]){
                intraffic_sum += var;
            }
            for(auto & var: node_outtraffic_map_vars[node_str]){
                outtraffic_sum += var;
            }
            if (node_str == flow_src) {
                // the src node, outtraffic_sum = src_agg_flow_size
                model.addConstr(outtraffic_sum == src_agg_flow_size);
            }
            else if (node_dsttraffic.find(node_str) != node_dsttraffic.end()){
                // dst node for some flow
                if (l3node_map_stub[node_str]) {
                    // stub node, avoid go-through traffic
                    model.addConstr(intraffic_sum == node_dsttraffic[node_str]);
                    model.addConstr(outtraffic_sum == 0);
                }
                else {
                    // non stub node, perimit go-through traffic
                    outtraffic_sum += node_dsttraffic[node_str];
                    model.addConstr(intraffic_sum == outtraffic_sum);
                }
            }
            else {
                // not src node, nor dst node for any flow
                // the go-through node
                if (l3node_map_stub[node_str]) {
                    // stub node, avoid go-through traffic
                    model.addConstr(intraffic_sum == 0);
                    model.addConstr(outtraffic_sum == 0);
                }
                else {
                    // non stub node, perimit go-through traffic
                    model.addConstr(intraffic_sum == outtraffic_sum);
                }
            }
        }
    }
    
    // add link capacity constraints
    for(auto & edge_it: py::list(g.attr("edges"))){
        py::tuple edge = py::tuple(py::reinterpret_borrow<py::object>(edge_it));
        std::string link_name = std::string(py::str(edge[0])) + "_" + std::string(py::str(edge[1]));
        GRBLinExpr link_traffic_aggr = 0;
        for(auto & var: link_map_vars[link_name]) {
            link_traffic_aggr += var;
        }
        py::object get_edge_data = g.attr("get_edge_data");
        py::dict temp = get_edge_data(*edge);

        int link_capa = stod(std::string(py::str(temp["capacity"])));
        double link_capa_adjust = link_capa * float(load_factor);
        model.addConstr(link_traffic_aggr <= link_capa_adjust);
        original_link_capacity[link_name] = std::make_pair(link_capa_adjust, link_traffic_aggr);
    }

    // adjust link capacity  constraints to failures
    for(auto & map_iter : failures){
        py::dict map = py::dict(py::reinterpret_borrow<py::object>(map_iter));
        while(!capacity_constr.empty()){
            model.remove(capacity_constr[capacity_constr.size()-1]);
            capacity_constr.pop_back();
        }
        model.reset();
        for(auto & src : map){
            for(auto & dst : py::dict(py::reinterpret_borrow<py::object>(src.second))){
                std::string src_dst = std::string(py::str(src.first)) + "_" + std::string(py::str(dst.first));
                std::string dst_src = std::string(py::str(dst.first)) + "_" + std::string(py::str(src.first));
                int capa_delta = stod(std::string(py::str(dst.second)));
                double capa_delta_adjust = capa_delta * float(load_factor);
                capacity_constr.push_back(model.addConstr(original_link_capacity[src_dst].second <= original_link_capacity[src_dst].first - capa_delta_adjust));
                capacity_constr.push_back(model.addConstr(original_link_capacity[dst_src].second <= original_link_capacity[dst_src].first - capa_delta_adjust));
            }
        }
        model.optimize();
        opt_cnt++;

        if(model.get(GRB_IntAttr_Status) != GRB_OPTIMAL) {
            return std::make_tuple(false, opt_cnt);
        }
    }
    return std::make_tuple(true, opt_cnt);
}


// flow formulation (FF)
std::tuple<bool, int> check(py::object graph, py::list failures, py::dict traffic_mattrix, py::dict node_stub, py::float_ load_factor){
    // Create an environment
    GRBEnv env = GRBEnv();

    // Create an empty model
    GRBModel model = GRBModel(env);
    int opt_cnt  = 0;
    py::object g = py::module::import("networkx").attr("DiGraph");
    g = graph;
    std::unordered_map<std::string, double> node_srctraffic;
    std::unordered_map<std::string, double> node_dsttraffic;
    std::unordered_map<std::string, std::vector<GRBVar>> node_intraffic_map_vars;
    std::unordered_map<std::string, std::vector<GRBVar>> node_outtraffic_map_vars;
    std::unordered_map<std::string, std::vector<GRBLinExpr>> link_map_vars;

    std::unordered_map<std::string, std::pair<double, GRBLinExpr>> original_link_capacity;
    std::unordered_map<std::string, bool> l3node_map_stub;
    std::vector<GRBConstr> capacity_constr;

    for (auto item : node_stub) {
        l3node_map_stub[std::string(py::str(item.first))] = item.second.cast<bool>();
    };

    int flow_idx = 0;
    for(auto & src : traffic_mattrix){
        for(auto dst: py::dict(py::reinterpret_borrow<py::object>(src.second))){
            std::string flow_src = std::string(py::str(src.first));
            std::string flow_dst = std::string(py::str(dst.first));
            int flow_size = stod(std::string(py::str(dst.second)));
            node_intraffic_map_vars.clear();
            node_outtraffic_map_vars.clear();
            for(auto & edge_it: py::list(g.attr("edges"))){
                py::tuple edge = py::tuple(py::reinterpret_borrow<py::object>(edge_it));
                std::string src_str = std::string(py::str(edge[0]));
                std::string dst_str = std::string(py::str(edge[1]));
                std::string link_name = src_str + "_" + dst_str;
                std::string var_name = std::to_string(flow_idx) + link_name;

                GRBVar lp_var = model.addVar(0.0, GRB_INFINITY, 0.0, GRB_CONTINUOUS, var_name);
                node_outtraffic_map_vars[src_str].push_back(lp_var);
                node_intraffic_map_vars[dst_str].push_back(lp_var);
                link_map_vars[link_name].push_back(lp_var);
            }
            for(auto & node: py::list(g.attr("nodes"))){
                std::string node_str = std::string(py::str(node));
                GRBLinExpr intraffic_sum = 0;
                GRBLinExpr outtraffic_sum = 0;
                for(auto & var: node_intraffic_map_vars[node_str]){
                    intraffic_sum += var;
                }
                for(auto & var: node_outtraffic_map_vars[node_str]){
                    outtraffic_sum += var;
                }

                if (node_str == flow_src) {
                    // the src node, outtraffic_sum = flow_size
                    model.addConstr(outtraffic_sum == flow_size);
                    model.addConstr(intraffic_sum == 0);
                }
                else if (node_str == flow_dst) {
                    // the dst node, intraffic_sum = flow_size
                    model.addConstr(intraffic_sum == flow_size);
                    model.addConstr(outtraffic_sum == 0);
                }
                else {
                    // the go-through node
                    if (l3node_map_stub[node_str]) {
                        // stub node, avoid go-through traffic
                        model.addConstr(intraffic_sum == 0);
                        model.addConstr(outtraffic_sum == 0);
                    }
                    else {
                        // non stub node, perimit go-through traffic
                        model.addConstr(intraffic_sum == outtraffic_sum);
                    }
                }
            }
            flow_idx += 1;
        }
    }
    
    // add link capacity constraints
    for(auto & edge_it: py::list(g.attr("edges"))){
        py::tuple edge = py::tuple(py::reinterpret_borrow<py::object>(edge_it));
        std::string link_name = std::string(py::str(edge[0])) + "_" + std::string(py::str(edge[1]));
        GRBLinExpr link_traffic_aggr = 0;
        for(auto & var: link_map_vars[link_name]) {
            link_traffic_aggr += var;
        }
        py::object get_edge_data = g.attr("get_edge_data");
        py::dict temp = get_edge_data(*edge);

        int link_capa = stod(std::string(py::str(temp["capacity"])));
        double link_capa_adjust = link_capa * float(load_factor);
        model.addConstr(link_traffic_aggr <= link_capa_adjust);
        original_link_capacity[link_name] = std::make_pair(link_capa_adjust, link_traffic_aggr);
    }

    // adjust link capacity  constraints to failures
    for(auto & map_iter : failures){
        py::dict map = py::dict(py::reinterpret_borrow<py::object>(map_iter));
        while(!capacity_constr.empty()){
            model.remove(capacity_constr[capacity_constr.size()-1]);
            capacity_constr.pop_back();
        }
        model.reset();
        for(auto & src : map){
            for(auto & dst : py::dict(py::reinterpret_borrow<py::object>(src.second))){
                std::string src_dst = std::string(py::str(src.first)) + "_" + std::string(py::str(dst.first));
                std::string dst_src = std::string(py::str(dst.first)) + "_" + std::string(py::str(src.first));
                int capa_delta = stod(std::string(py::str(dst.second)));
                double capa_delta_adjust = capa_delta * float(load_factor);
                capacity_constr.push_back(model.addConstr(original_link_capacity[src_dst].second <= original_link_capacity[src_dst].first - capa_delta_adjust));
                capacity_constr.push_back(model.addConstr(original_link_capacity[dst_src].second <= original_link_capacity[dst_src].first - capa_delta_adjust));
            }
        }
        model.optimize();
        opt_cnt++;

        if(model.get(GRB_IntAttr_Status) != GRB_OPTIMAL) {
            return std::make_tuple(false, opt_cnt);
        }
    }
    return std::make_tuple(true, opt_cnt);
}

std::tuple<int, int, std::unordered_map<int, int>> ilp_solve_c(py::object graph, py::list failures, py::dict steady_tm, py::dict failures_tm, py::dict fibers,
    py::dict node_stub, py::float_ load_factor, unsigned int step_size, long int timelimit, py::float_ mipgapabs){

    // Create an environment
    GRBEnv env = GRBEnv();
    if (timelimit > 0) {
        env.set(GRB_DoubleParam_TimeLimit, timelimit);
    }
    env.set(GRB_DoubleParam_MIPGapAbs, float(mipgapabs));

    // Create an empty model
    GRBModel model = GRBModel(env);
    model.set(GRB_IntParam_DualReductions, 0);
    GRBLinExpr obj = 0.0;

    py::object g = py::module::import("networkx").attr("Graph");
    g = graph;
    std::unordered_map<std::string, double> node_srctraffic;
    std::unordered_map<std::string, double> node_dsttraffic;
    std::unordered_map<std::string, std::vector<GRBVar>> node_intraffic_map_vars;
    std::unordered_map<std::string, std::vector<GRBVar>> node_outtraffic_map_vars;
    std::unordered_map<std::string, std::vector<GRBLinExpr>> node_pair_map_traffic_vars;

    std::unordered_map<std::string, std::pair<double, GRBLinExpr>> original_link_capacity;
    std::unordered_map<std::string, bool> l3node_map_stub;
    std::vector<GRBConstr> capacity_constr;

    std::unordered_map<std::string, GRBVar> link_map_var;
    std::unordered_map<std::pair<std::string, std::string>, std::vector<std::pair<int, GRBVar>>, boost::hash<std::pair<std::string, std::string>>> node_pair_map_capa_vars;
    std::unordered_map<std::string, std::vector<std::pair<int, GRBVar>>> lease_capa_map_capa_vars;
    std::unordered_map<std::string, std::vector<std::tuple<float, int, GRBVar>>> fiber_spectrum_map_capa_vars;
    
    // <fiber_name, <lease_flag, max_bw, max_spectrum>>
    std::unordered_map<std::string, std::tuple<bool,int, int>> fiber_map_max_cstr;

    std::set<std::pair<std::string, std::string>> complete_node_pair;

    // handle stub node
    for (auto item : node_stub) {
        l3node_map_stub[std::string(py::str(item.first))] = item.second.cast<bool>();
    };
    
    // parse fiber max_constraints
    for (auto fiber_item : fibers) {
        std::string fiber_name = std::string(py::str(fiber_item.first));
        py::tuple tuple_py = py::reinterpret_borrow<py::object>(fiber_item.second);
        bool lease_flag = tuple_py[0].cast<bool>();
        int max_bw = tuple_py[1].cast<int>();
        int max_spectrum = tuple_py[2].cast<int>();
        fiber_map_max_cstr[fiber_name] = std::make_tuple(lease_flag, max_bw, max_spectrum);
    }
    
    // set the relationship between l3 link capas and (src, dst) bandwidth
    // also record the capa or spectrum of underlying fibers
    py::object get_edge_data = g.attr("get_edge_data");
    for(auto & edge_it: py::list(g.attr("edges"))){
        py::tuple edge = py::tuple(py::reinterpret_borrow<py::object>(edge_it));
        py::dict temp = get_edge_data(*edge);

        int link_capa = stod(std::string(py::str(temp["capacity"])));
        int max_delta_step = stod(std::string(py::str(temp["max_delta_step"])));
        
        std::string link_name = std::string(py::str(temp["name"]));
        GRBVar link_delta_var = model.addVar(0, GRB_INFINITY, 0, GRB_INTEGER, link_name);
        link_map_var[link_name] = link_delta_var;
        std::string src_str = std::string(py::str(edge[0]));
        std::string dst_str = std::string(py::str(edge[1]));

        node_pair_map_capa_vars[std::make_pair(src_str, dst_str)].push_back(std::make_pair(link_capa,link_delta_var));
        node_pair_map_capa_vars[std::make_pair(dst_str, src_str)].push_back(std::make_pair(link_capa,link_delta_var));

        complete_node_pair.insert(std::make_pair(src_str, dst_str));
        complete_node_pair.insert(std::make_pair(dst_str, src_str));

        if (max_delta_step >= 0) {
            model.addConstr(link_delta_var <= max_delta_step);
        }
        
        int link_cost = stod(std::string(py::str(temp["cost"])));
        obj += link_cost * step_size * link_delta_var;
        // fiber constraints related
        for (auto & fiber_item : py::dict(temp["fiber_map_spectrum"])) {
            std::string fiber_name = std::string(py::str(fiber_item.first));
            float spectrum_eff = std::stod(std::string(py::str(fiber_item.second)));
            if (std::get<0>(fiber_map_max_cstr[fiber_name])) {
                //lease_flag = true; check the max_capa in Leases
                lease_capa_map_capa_vars[fiber_name].push_back(std::make_pair(link_capa, link_delta_var));
            }
            else {
                //lease_flag = false; check the spectrum in Fibers
                fiber_spectrum_map_capa_vars[fiber_name].push_back(std::make_tuple(spectrum_eff, link_capa, link_delta_var));
            }
        }
    }

    // add lease capa constraints
    for (auto it : lease_capa_map_capa_vars) {
        std::string lease_name = it.first;
        int max_capa = std::get<1>(fiber_map_max_cstr[lease_name]);
        GRBLinExpr lease_capa = 0;
        for (auto & var: it.second) {
            lease_capa += var.first;
            lease_capa += step_size*var.second;
        }
        
        model.addConstr(lease_capa <= max_capa);
    }

    // add fiber spectrum constraints
    for (auto it : fiber_spectrum_map_capa_vars) {
        std::string fiber_name = it.first;
        int max_spectrum = std::get<2>(fiber_map_max_cstr[fiber_name]);
        GRBLinExpr fiber_spectrum = 0;
        for (auto & var: it.second) {
            fiber_spectrum += std::get<1>(var)*std::get<0>(var);
            fiber_spectrum += std::get<2>(var)*std::get<0>(var)*step_size;
        }
        model.addConstr(fiber_spectrum <= max_spectrum);
    }

    /***
    add the constraints for steady state
    ***/
    // in-out balance for source-aggr formulation
    node_pair_map_traffic_vars.clear();
    for(auto & src : steady_tm){
        std::string flow_src = std::string(py::str(src.first));
        float src_agg_flow_size = 0;
        node_dsttraffic.clear();
        node_intraffic_map_vars.clear();
        node_outtraffic_map_vars.clear();

        for(auto dst: py::dict(py::reinterpret_borrow<py::object>(src.second))){
            src_agg_flow_size += stod(std::string(py::str(dst.second)));
            node_dsttraffic[std::string(py::str(dst.first))] = stod(std::string(py::str(dst.second)));
        }
        
        for(auto node_pair : complete_node_pair) {
            std::string src_str = node_pair.first;
            std::string dst_str = node_pair.second;
            std::string node_pair_name = src_str + "_" + dst_str;
            std::string var_name = "steady" + flow_src + "flow_src" + node_pair_name;

            GRBVar lp_var = model.addVar(0.0, GRB_INFINITY, 0.0, GRB_CONTINUOUS, var_name);
            node_outtraffic_map_vars[src_str].push_back(lp_var);
            node_intraffic_map_vars[dst_str].push_back(lp_var);
            node_pair_map_traffic_vars[node_pair_name].push_back(lp_var); 
        }
        for(auto & node: py::list(g.attr("nodes"))){
            std::string node_str = std::string(py::str(node));
            GRBLinExpr intraffic_sum = 0;
            GRBLinExpr outtraffic_sum = 0;
            for(auto & var: node_intraffic_map_vars[node_str]){
                intraffic_sum += var;
            }
            for(auto & var: node_outtraffic_map_vars[node_str]){
                outtraffic_sum += var;
            }
            if (node_str == flow_src) {
                // the src node, outtraffic_sum = src_agg_flow_size
                model.addConstr(outtraffic_sum == src_agg_flow_size);
            }
            else if (node_dsttraffic.find(node_str) != node_dsttraffic.end()){
                // dst node for some flow
                if (l3node_map_stub[node_str]) {
                    // stub node, avoid go-through traffic
                    model.addConstr(intraffic_sum == node_dsttraffic[node_str]);
                    model.addConstr(outtraffic_sum == 0);
                }
                else {
                    // non stub node, perimit go-through traffic
                    outtraffic_sum += node_dsttraffic[node_str];
                    model.addConstr(intraffic_sum == outtraffic_sum);
                }
            }
            else {
                // not src node, nor dst node for any flow
                // the go-through node
                if (l3node_map_stub[node_str]) {
                    // stub node, avoid go-through traffic
                    model.addConstr(intraffic_sum == 0);
                    model.addConstr(outtraffic_sum == 0);
                }
                else {
                    // non stub node, perimit go-through traffic
                    model.addConstr(intraffic_sum == outtraffic_sum);
                }
            }
        }
    }
    
    // add link capacity constraints
    for(auto node_pair : node_pair_map_capa_vars) {
        std::string src_str = node_pair.first.first;
        std::string dst_str = node_pair.first.second;
        std::string link_name = src_str + "_" + dst_str;
        GRBLinExpr link_traffic_aggr = 0;
        GRBLinExpr link_capa_aggr = 0;
        for(auto & var: node_pair_map_traffic_vars[link_name]) {
            link_traffic_aggr += var;
        }

        for(auto & var: node_pair_map_capa_vars[std::make_pair(src_str, dst_str)]) {
            // add init capa
            link_capa_aggr += int(var.first*float(load_factor));

            // add capa vars
            link_capa_aggr += int(step_size*float(load_factor))*var.second; 
        }
        model.addConstr(link_traffic_aggr <= link_capa_aggr);
    }

    /***
    add the constraints for each failure
    ***/
    int failure_idx = -1;
    for(auto & list_iter : failures){
        failure_idx += 1;
        // in-out balance for source-aggr formulation
        node_pair_map_traffic_vars.clear();
        for(auto & src : failures_tm){
            std::string flow_src = std::string(py::str(src.first));
            float src_agg_flow_size = 0;
            node_dsttraffic.clear();
            node_intraffic_map_vars.clear();
            node_outtraffic_map_vars.clear();

            for(auto dst: py::dict(py::reinterpret_borrow<py::object>(src.second))){
                src_agg_flow_size += stod(std::string(py::str(dst.second)));
                node_dsttraffic[std::string(py::str(dst.first))] = stod(std::string(py::str(dst.second)));
            }
            
            for(auto node_pair : complete_node_pair) {
                std::string src_str = node_pair.first;
                std::string dst_str = node_pair.second;
                std::string node_pair_name = src_str + "_" + dst_str;
                std::string var_name = "spof" + std::to_string(failure_idx) + flow_src + "flow_src" + node_pair_name;
                GRBVar lp_var = model.addVar(0.0, GRB_INFINITY, 0.0, GRB_CONTINUOUS, var_name);
                node_outtraffic_map_vars[src_str].push_back(lp_var);
                node_intraffic_map_vars[dst_str].push_back(lp_var);
                node_pair_map_traffic_vars[node_pair_name].push_back(lp_var); 
            }
            for(auto & node: py::list(g.attr("nodes"))){
                std::string node_str = std::string(py::str(node));
                GRBLinExpr intraffic_sum = 0;
                GRBLinExpr outtraffic_sum = 0;
                for(auto & var: node_intraffic_map_vars[node_str]){
                    intraffic_sum += var;
                }
                for(auto & var: node_outtraffic_map_vars[node_str]){
                    outtraffic_sum += var;
                }
                if (node_str == flow_src) {
                    // the src node, outtraffic_sum = src_agg_flow_size
                    model.addConstr(outtraffic_sum == src_agg_flow_size);
                }
                else if (node_dsttraffic.find(node_str) != node_dsttraffic.end()){
                    // dst node for some flow
                    if (l3node_map_stub[node_str]) {
                        // stub node, avoid go-through traffic
                        model.addConstr(intraffic_sum == node_dsttraffic[node_str]);
                        model.addConstr(outtraffic_sum == 0);
                    }
                    else {
                        // non stub node, perimit go-through traffic
                        outtraffic_sum += node_dsttraffic[node_str];
                        model.addConstr(intraffic_sum == outtraffic_sum);
                    }
                }
                else {
                    // not src node, nor dst node for any flow
                    // the go-through node
                    if (l3node_map_stub[node_str]) {
                        // stub node, avoid go-through traffic
                        model.addConstr(intraffic_sum == 0);
                        model.addConstr(outtraffic_sum == 0);
                    }
                    else {
                        // non stub node, perimit go-through traffic
                        model.addConstr(intraffic_sum == outtraffic_sum);
                    }
                }
            }
        }
        
        std::vector<std::string> failed_links_list = py::list(py::reinterpret_borrow<py::object>(list_iter)).cast<std::vector<std::string>>();

        // recompute node_pair_map_capa_vars because of the failure
        node_pair_map_capa_vars.clear();
        for(auto & edge_it: py::list(g.attr("edges"))){
            py::tuple edge = py::tuple(py::reinterpret_borrow<py::object>(edge_it));
            py::dict temp = get_edge_data(*edge);

            int link_capa = stod(std::string(py::str(temp["capacity"])));
            
            std::string link_name = std::string(py::str(temp["name"]));
            
            std::string src_str = std::string(py::str(edge[0]));
            std::string dst_str = std::string(py::str(edge[1]));
            
            if(std::find(failed_links_list.begin(), failed_links_list.end(), link_name) == failed_links_list.end()) {
                // not in the failed link vector
                node_pair_map_capa_vars[std::make_pair(src_str, dst_str)].push_back(std::make_pair(link_capa,link_map_var[link_name]));
                node_pair_map_capa_vars[std::make_pair(dst_str, src_str)].push_back(std::make_pair(link_capa,link_map_var[link_name]));
            }
        }
        

        // add link capacity constraints
        for(auto node_pair : complete_node_pair) {
            std::string src_str = node_pair.first;
            std::string dst_str = node_pair.second;
            std::string link_name = src_str + "_" + dst_str;
            GRBLinExpr link_traffic_aggr = 0;
            GRBLinExpr link_capa_aggr = 0;
            for(auto & var: node_pair_map_traffic_vars[link_name]) {
                link_traffic_aggr += var;
            }

            if (node_pair_map_capa_vars.find(std::make_pair(src_str, dst_str)) != node_pair_map_capa_vars.end()) {
                // the node_pair that has capacity under failure
                for(auto & var: node_pair_map_capa_vars[std::make_pair(src_str, dst_str)]) {
                    // add init capa
                    link_capa_aggr += int(var.first*float(load_factor));

                    // add capa vars
                    link_capa_aggr += int(step_size*float(load_factor))*var.second; 
                }
            }
            model.addConstr(link_traffic_aggr <= link_capa_aggr);
        }
    }
    model.setObjective(obj, GRB_MINIMIZE);
    model.optimize();
    int sum_delta_capa = 0;
    std::unordered_map<int, int> opt_sol;
    if(model.get(GRB_IntAttr_Status) == GRB_OPTIMAL) {
        std::cout << "Obj: " << model.get(GRB_DoubleAttr_ObjVal) << std::endl;
        std::string sol_dict = "{";    
        // print the solution
        for(auto & edge_it: py::list(g.attr("edges"))) {
            py::tuple edge = py::tuple(py::reinterpret_borrow<py::object>(edge_it));
            py::dict temp = get_edge_data(*edge);
            std::string link_name = std::string(py::str(temp["name"]));

            int link_capa = stod(std::string(py::str(temp["capacity"])));
            int link_idx = stod(std::string(py::str(temp["idx"])));
            int var_value = round(link_map_var[link_name].get(GRB_DoubleAttr_X));
            if (var_value > 0) {
                sum_delta_capa += step_size*var_value;
                opt_sol[link_idx] = var_value;
            }
            int link_final_capa = link_capa + step_size*var_value;
            sol_dict += "\"" + link_name + "\":" + std::to_string(link_final_capa) + ", ";
        }
        sol_dict = sol_dict.substr(0, sol_dict.size()-2) + "}";
        std::ofstream ilp_sol("ilp_sol.txt");
        ilp_sol << sol_dict;
        ilp_sol.close();
        std::cout << "sum_delta_capa: " << sum_delta_capa << std::endl;
        return std::make_tuple(model.get(GRB_DoubleAttr_ObjVal), sum_delta_capa, opt_sol);
    }
    else {
        std::cout << "don't get the GRB_OPTIMAL:" << model.get(GRB_IntAttr_Status) <<std::endl;
        return std::make_tuple(-1, sum_delta_capa, opt_sol);
    }
}

PYBIND11_MODULE(gurobi_c, m) {
    m.def("check_sf", &check_sf, "Checks if traffic matrix is feasible under topology", py::arg("g"), py::arg("failures"), py::arg("tm"), py::arg("stub"), py::arg("load_factor"));
    m.def("check", &check, "Checks if traffic matrix is feasible under topology", py::arg("g"), py::arg("failures"), py::arg("tm"), py::arg("stub"), py::arg("load_factor"));
    m.def("ilp_solve_c", &ilp_solve_c, "ilp solver", py::arg("g"), py::arg("failures"), py::arg("steady_tm"), py::arg("failures_tm"), 
        py::arg("fibers"), py::arg("stub"), py::arg("load_factor"), py::arg("step_size"), py::arg("timelimit"), py::arg("mipabsgap"));
}
