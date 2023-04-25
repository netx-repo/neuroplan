# Open the input and output files
input_datapath = 'topologies/VisionNet.gml'
output_datapath = 'topologies/VisionNet_with_label_unique.gml'

with open(input_datapath, "r") as f_in, open(output_datapath, "w") as f_out:
    # Loop through the lines in the input file
# Loop through the lines in the input file
    for line in f_in:
        # Check if this line defines a node
        if line.strip().startswith("node ["):
            # Read the node attributes
            node_id = None
            label = None
            other_attrs = {}
            for line in f_in:
                if line.strip() == "]":
                    break
                elif line.strip().startswith("id"):
                    node_id = int(line.strip().split()[1])
                elif line.strip().startswith("label"):
                    label = line.strip().split()[1][1:-1]  # remove quotes
                else:
                    # Store any other attributes in a dictionary
                    attr_name, attr_value = line.strip().split(maxsplit=1)
                    other_attrs[attr_name] = attr_value
            # Modify the label attribute to include the node ID
            if node_id is not None and label is not None:
                label = f"{label}_{node_id}"
            # Write the modified node definition to the output file
            f_out.write("  node [\n")
            f_out.write(f"    id {node_id}\n")
            if label is not None:
                f_out.write(f"    label \"{label}\"\n")
            for attr_name, attr_value in other_attrs.items():
                f_out.write(f"    {attr_name} {attr_value}\n")
            f_out.write("  ]\n")
        else:
            # Write this line to the output file
            f_out.write(line)



# #import networkx as nx

# #filepath = 'Kdl.graph'

# import networkx as nx
# from networkx.readwrite.gml import parse_gml

# # Parse the GML file into a dictionary
# with open("Kdl.graph") as f:
#     graph_dict = parse_gml(f)

# # Add the "label_unique" field to each node
# for node in graph_dict["nodes"].values():
#     label = node.get("label")
#     if label is not None:
#         node["label_unique"] = f"{label}_{node['id']}"
#     else:
#         node["label_unique"] = f"{node['id']}"

# # Create the networkx graph object from the modified dictionary

