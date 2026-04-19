import os
import re
import networkx as nx
from networkx.drawing.nx_pydot import graphviz_layout

from config import BB_LINES_MAP_FILE

def load_bb_lines_map(file_path):
    """
    Parses bb_lines_map.txt and returns a dictionary mapping bb_id to (filename, start, end).
    """
    bb_map = {}
    if not os.path.exists(file_path):
        return bb_map
    
    # Pattern: %bb_id,filename,start,end
    pattern = re.compile(r"%?(\w+),([^,]+),(\d+),(\d+)")
    try:
        with open(file_path, "r") as f:
            for line in f:
                match = pattern.search(line)
                if match:
                    bb_id, filename, start, end = match.groups()
                    bb_map[bb_id] = (filename, start, end)
    except Exception as e:
        print(f"Error reading BB map file: {e}")
    return bb_map

def load_target_bb_map(file_path):
    """
    Parses target_bb_map.txt and returns a dictionary mapping target_id to bb_id.
    """
    target_bb_map = {}
    if not os.path.exists(file_path):
        return target_bb_map
    
    # Pattern: target_id,%bb_id
    pattern = re.compile(r"(\d+),%?(\w+)")
    try:
        with open(file_path, "r") as f:
            for line in f:
                match = pattern.search(line)
                if match:
                    t_id, bb_id = match.groups()
                    target_bb_map[int(t_id)] = bb_id
    except Exception as e:
        print(f"Error reading target BB map file: {e}")
    return target_bb_map

def load_cfg_adj(file_path):
    """
    Parses a CFG edge file and returns a dictionary mapping bb_id to a list of successor bb_ids.
    """
    adj = {}
    if not os.path.exists(file_path):
        return adj

    # Pattern for lines such as: %node1, %node2, [label]
    edge_pattern = re.compile(r"%?([\w\.]+),\s*%?([\w\.]+),\s*\[(.*)\]")
    
    try:
        with open(file_path, "r") as f:
            for line in f:
                match = edge_pattern.search(line)
                if match:
                    u, v, cond = match.groups()
                    if u not in adj:
                        adj[u] = []
                    if v not in adj[u]:
                        adj[u].append(v)
    except Exception as e:
        print(f"Error reading CFG file for adjacency: {e}")
    
    # adj contains: {bb_id: [succ_bb_id1, succ_bb_id2, ...], bb_id2: [...], ...}
    return adj

def load_cfg_with_graphviz(file_path, top_n=0):
    G = nx.DiGraph()
    edges_info = []
    bb_map = load_bb_lines_map(BB_LINES_MAP_FILE)
    edge_pattern = re.compile(r"%?([\w\.]+),\s*%?([\w\.]+),\s*\[(.*)\]")
    
    if not os.path.exists(file_path):
        return []
    
    with open(file_path, "r") as f:
        for line in f:
            match = edge_pattern.search(line)
            if match:
                u, v, cond = match.groups()
                color = "#888"
                if "(T)" in cond: color = "#28a745"
                elif "(F)" in cond: color = "#dc3545"
                
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
        label = f"BB {node_id}"
        if node_id in bb_map:
            file, start, end = bb_map[node_id]
            label = f"{file}:{start}-{end} ({node_id})"
            
        all_nodes.append({
            'data': {'id': node_id, 'label': label},
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