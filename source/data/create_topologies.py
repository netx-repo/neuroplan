import random
import networkx as nx
import pandas as pd

def max_flow_computation(Gbase, capacity_max):
    max_capacities = dict(zip(list(Gbase.edges), [capacity_max] * len(list(Gbase.edges))))
    nx.set_edge_attributes(Gbase, max_capacities, 'capacity')
    rand_source = list(Gbase.nodes)[random.randint(0, len(list(Gbase.nodes)))]
    rand_term = list(Gbase.nodes)[random.randint(0, len(list(Gbase.nodes)))]
    R = nx.max_flow_min_cost(Gbase, rand_source, rand_term)
    flows = {}
    G_copy = Gbase.copy()
    for edge in G_copy.edges:
        flows[(edge[0], edge[1])] = R[edge[0]][edge[1]]
    
    nx.set_edge_attributes(Gbase, flows, 'actual_capacity')


def process_graph_from_topology(file_path, 
                                excel_path, 
                                rtt_min, 
                                rtt_max, 
                                capacity_min, 
                                capacity_max, 
                                ip_capacity_final,
                                sample_bounds,
                                fp_max, 
                                spectrum_size, 
                                max_flow_flag=False):

    # leases and fibers stuff

    Gbase = nx.read_gml(file_path)

    if max_flow_flag:
        Gbase = nx.DiGraph(Gbase)
        max_flow_computation(Gbase, capacity_max)

    source_list = []
    dest_list = []
    rtt_list = []
    capacity_min_list = []
    capacity_max_list = []
    actual_capacity_list = []
    link_names_list = []
    cos_list = []

    max_fp_list = []
    spectrum_size_ghz_per_fp_list = []

    for i, edge in enumerate(Gbase.edges):
        source_list.append(edge[0])
        dest_list.append(edge[1])
        rtt_list.append(random.randint(rtt_min, rtt_max))
        capacity_min_list.append(capacity_min)
        capacity_max_list.append(capacity_max)
        link_names_list.append("Link_{}".format(i))

        cos_list.append('BRONZE') # not entirely sure what this is

        if max_flow_flag:
            actual_capacity_list.append(Gbase.edges[edge]['actual_capacity'])
        else:
            actual_capacity_list.append(random.randint(*sample_bounds))

        max_fp_list.append(fp_max)
        spectrum_size_ghz_per_fp_list.append(spectrum_size)

    rtt_capacity_df = pd.DataFrame({
        'LinkName' : link_names_list,
        'Source' : source_list,
        'Destination' : dest_list,
        'RTT' : rtt_list,
        'CapacityMin' : capacity_min_list,
        'CapacityMax' : capacity_max_list,
    })

    flows_df = pd.DataFrame({
        'LinkName' : link_names_list,
        'Source' : source_list,
        'Destination' : dest_list,
        'COS' : cos_list,
        'ActualCapacity' : actual_capacity_list,
    })

    fibers_df = pd.DataFrame({
        'name' : link_names_list,
        'src' : source_list, 
        'dst' : dest_list,
        'rtt' : rtt_list,
        'max_fp' : max_fp_list,
        'spectrum_size_ghz_per_fp' : spectrum_size_ghz_per_fp_list
    })
    
    # ip, l3 stuff

    nodes = list(Gbase.nodes)
    IPGraph = Gbase.copy()

    ip_name_arr = nodes.copy()
    ip_l1_node_arr = nodes.copy()
    ip_stub_arr = ['FALSE'] * len(nodes)

    ip_source_list = []
    ip_dest_list = []
    ip_capacity_min_list = []
    ip_capacity_max_list = []
    ip_actual_capacity_list = []
    ip_link_names_list = []
    ip_fiber_name_map_spectrum_list = []
    igp_list = []

    for i, edge in enumerate(IPGraph.edges):
        ip_source_list.append(edge[0])
        ip_dest_list.append(edge[1])
        ip_capacity_min_list.append(capacity_min)
        ip_capacity_max_list.append(capacity_max)
        ip_link_names_list.append("ip_Link_{}".format(i))
        ip_fiber_name_map_spectrum_list.append("Link_{}:5".format(i))
        igp_list.append(0)
        
        if max_flow_flag:
            ip_actual_capacity_list.append(IPGraph.edges[edge]['actual_capacity'])
        else:
            ip_actual_capacity_list.append(ip_capacity_final) 
    
    ip_capacity_df = pd.DataFrame({
        'name' : ip_link_names_list,
        'src' : ip_source_list,
        'dst' : ip_dest_list,
        'min_capacity_gbps' : ip_capacity_min_list,
        'max_capacity_gbps' : ip_capacity_max_list,
        'final_capacity_gpbs' : ip_actual_capacity_list,
        'igp' : igp_list,
        'fiber_name_map_spectrum' : ip_fiber_name_map_spectrum_list,
    })

    ip_names_df = pd.DataFrame({
        'name' : ip_name_arr,
        'l1_node' : ip_l1_node_arr,
        'stub' : ip_stub_arr,
    })

    spofs_df = pd.DataFrame({
        'fiber_names' : [],
        'cos_to_protect' : [],
    })
    
    with pd.ExcelWriter(excel_path) as writer:
        rtt_capacity_df.to_excel(writer, sheet_name='RTT-Capacity')
        fibers_df.to_excel(writer, sheet_name='Fibers')
        flows_df.to_excel(writer, sheet_name='Flows')
        ip_names_df.to_excel(writer, sheet_name='L3Nodes')
        ip_capacity_df.to_excel(writer, sheet_name='L3Links')
        spofs_df.to_excel(writer, sheet_name='Spofs')

if __name__ == '__main__':
    file_path = 'topologies/gml_files/Cogentco_with_label_unique.gml'
    excel_path = 'topologies/random_sampled_topos/Cogentco_topology.xlsx'
    rtt_min = 2
    rtt_max = 5
    capacity_min = 0
    capacity_max = 1000
    ip_capacity_final = 20
    sample_bounds = (750, 950)
    fp_max = 50
    spectrum_size = 10
    max_flow_flag = False
    process_graph_from_topology(file_path, 
                                excel_path, 
                                rtt_min, 
                                rtt_max, 
                                capacity_min, 
                                capacity_max, 
                                ip_capacity_final,
                                sample_bounds,
                                fp_max, 
                                spectrum_size,
                                max_flow_flag)