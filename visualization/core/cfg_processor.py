import os
import re

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