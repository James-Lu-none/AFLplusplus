import os
import re
import networkx as nx
from networkx.drawing.nx_pydot import graphviz_layout

def load_cfg_data(file_path):
    """
    Parses a CFG edge file and returns elements for Dash Cytoscape.
    """
    elements = []
    nodes = set()
    # Pattern for lines such as: %node1, %node2, [label]
    edge_pattern = re.compile(r"%?([\w\.]+),\s*%?([\w\.]+),\s*\[(.*)\]")
    
    if not os.path.exists(file_path):
        return []

    try:
        with open(file_path, "r") as f:
            for line in f:
                match = edge_pattern.search(line)
                if match:
                    u, v, cond = match.groups()
                    for node_id in [u, v]:
                        if node_id not in nodes:
                            elements.append({'data': {'id': node_id, 'label': f"BB {node_id}"}})
                            nodes.add(node_id)

                    color = "#888" # Default color
                    if "(TRUE)" in cond: 
                        color = "#28a745" # Success color
                    elif "(FALSE)" in cond: 
                        color = "#dc3545" # Error color
                    
                    elements.append({
                        'data': {
                            'source': u, 
                            'target': v, 
                            'label': cond if cond != "none" else "",
                            'color': color
                        }
                    })
    except Exception as e:
        print(f"Error reading CFG file: {e}")
        
    return elements

def load_cfg_with_graphviz(file_path, top_n=0):
    G = nx.DiGraph()
    edges_info = []
    edge_pattern = re.compile(r"%?([\w\.]+),\s*%?([\w\.]+),\s*\[(.*)\]")
    
    if not os.path.exists(file_path):
        return []
    
    with open(file_path, "r") as f:
        for line in f:
            match = edge_pattern.search(line)
            if match:
                u, v, cond = match.groups()
                color = "#888"
                if "(TRUE)" in cond: color = "#28a745"
                elif "(FALSE)" in cond: color = "#dc3545"
                
                G.add_edge(u, v)
                edges_info.append({'u': u, 'v': v, 'label': cond if cond != "none" else "", 'color': color})

    if len(G.nodes()) == 0:
        return []
    
    # 1. Calculate degree of all nodes
    # 2. Find top N nodes that has most number of degree
    if top_n > 0:
        degrees = dict(G.degree())
        sorted_nodes = sorted(degrees.items(), key=lambda x: x[1], reverse=True)
        top_n_nodes = [node for node, degree in sorted_nodes[:top_n]]
        
        # 3. remove related egdes for top N nodes from the graph
        # Actually, removing nodes also removes their edges in NetworkX
        print(f"Removing top {top_n} nodes: {top_n_nodes}")
        G.remove_nodes_from(top_n_nodes)
        
        # Also need to filter edges_info to remove those associated with top_n_nodes
        edges_info = [e for e in edges_info if e['u'] not in top_n_nodes and e['v'] not in top_n_nodes]

    if len(G.nodes()) == 0:
        return []

    # 4. proceed the original Graphviz layout 
    print(f"Calculating Graphviz layout for {len(G.nodes())} nodes and {len(G.edges())} edges...")
    try:
        pos = graphviz_layout(G, prog='dot')
    except Exception as e:
        print(f"Graphviz layout failed: {e}. Falling back to spring layout.")
        pos = nx.spring_layout(G)

    all_nodes = []
    for node_id in G.nodes():
        all_nodes.append({
            'data': {'id': node_id, 'label': f"BB {node_id}"},
            'position': {'x': pos[node_id][0], 'y': pos[node_id][1]*-1},
            'locked': True
        })

    all_edges = []
    for e in edges_info:
        all_edges.append({
            'data': {'source': e['u'], 'target': e['v'], 'label': e['label'], 'color': e['color']}
        })
    elements = all_nodes + all_edges
    return elements