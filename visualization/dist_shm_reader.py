import dash
from dash import html, dcc, Input, Output, State
import dash_cytoscape as cyto
import subprocess
import ctypes
import os
import re
import time

MAX_TARGETS = 64
MAX_SEED_SIZE = 512

class DistanceEntry(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("target_id", ctypes.c_uint32),
        ("min_distance", ctypes.c_uint32),
        ("last_bb_id", ctypes.c_uint32),
        ("seed_len", ctypes.c_uint32),
        ("is_active", ctypes.c_uint32),
        ("seed_content", ctypes.c_uint8 * MAX_SEED_SIZE),
    ]

class SharedDistKVStore(ctypes.Structure):
    _fields_ = [("entries", DistanceEntry * MAX_TARGETS)]

libc = ctypes.CDLL("libc.so.6")
shmat = libc.shmat
shmat.restype = ctypes.c_void_p

def get_afl_shm_ptr(target_name="target_normal", shm_name="AFL_DIST_KV_SHM_ID"):
    # try to find the shared memory ID from the environment variables of the running target_normal process
    try:
        pid_list = subprocess.check_output(["pidof", target_name]).decode().split()
        for pid in pid_list:
            with open(f"/proc/{pid}/environ", "rb") as f:
                env = f.read().split(b'\0')
                for e in env:
                    if shm_name.encode() in e:
                        shm_id = int(e.split(b"=")[1])
                        ptr = shmat(shm_id, None, 0)
                        return ptr if ptr != -1 else None
    except Exception as e:
        print(f"unable to find shared memory ID: {e}")
    return None

def load_cfg_data(file_path):
    elements = []
    nodes = set()
    edge_pattern = re.compile(r"%?([\w\.]+),\s*%?([\w\.]+),\s*\[(.*)\]")
    
    if not os.path.exists(file_path):
        return []

    with open(file_path, "r") as f:
        for line in f:
            match = edge_pattern.search(line)
            if match:
                u, v, cond = match.groups()
                for node_id in [u, v]:
                    if node_id not in nodes:
                        elements.append({'data': {'id': node_id, 'label': f"BB {node_id}"}})
                        nodes.add(node_id)

                color = "#888"
                if "(TRUE)" in cond: color = "#28a745"
                elif "(FALSE)" in cond: color = "#dc3545"
                
                elements.append({
                    'data': {
                        'source': u, 
                        'target': v, 
                        'label': cond if cond != "none" else "",
                        'color': color
                    }
                })
    return elements

app = dash.Dash(__name__)
dist_shm_ptr_global = get_afl_shm_ptr("target_normal", "AFL_DIST_KV_SHM_ID")

app.layout = html.Div(style={'backgroundColor': '#121212', 'color': 'white', 'height': '100vh', 'padding': '10px'}, children=[
    html.H2("AFL++ LLM-Guided Fuzzing Monitor", style={'textAlign': 'center'}),
    
    html.Div(style={'display': 'flex'}, children=[
        html.Div(style={'width': '70%'}, children=[
            cyto.Cytoscape(
                id='cfg-graph',
                elements=load_cfg_data("cfg_edges.txt"),
                layout={'name': 'breadthfirst', 'directed': True, 'spacingFactor': 1.5},
                style={'width': '100%', 'height': '750px', 'border': '1px solid #444'},
                stylesheet=[
                    {'selector': 'node', 'style': {'label': 'data(label)', 'color': 'white', 'background-color': '#007bff'}},
                    {'selector': 'edge', 'style': {
                        'label': 'data(label)', 'line-color': 'data(color)', 
                        'target-arrow-shape': 'triangle', 'curve-style': 'bezier',
                        'font-size': '10px', 'color': '#aaa', 'width': 2
                    }}
                ]
            )
        ]),
        
        html.Div(style={'width': '30%', 'padding': '20px', 'backgroundColor': '#1e1e1e', 'marginLeft': '10px'}, children=[
            html.H3("Live Status"),
            html.Div(id='live-status-info'),
            html.Hr(),
            html.H4("Clicked Node Info"),
            html.Div(id='node-data-display', style={'wordBreak': 'break-all', 'fontFamily': 'monospace', 'fontSize': '12px'})
        ])
    ]),
    
    dcc.Interval(id='refresh-timer', interval=1000, n_intervals=0)
])


@app.callback(
    [Output('cfg-graph', 'stylesheet'),
     Output('live-status-info', 'children')],
    [Input('refresh-timer', 'n_intervals')]
)
def update_live_data(n):
    global dist_shm_ptr_global
    if not dist_shm_ptr_global:
        dist_shm_ptr_global = get_afl_shm_ptr("target_normal", "AFL_DIST_KV_SHM_ID")
        if not dist_shm_ptr_global:
            return dash.no_update, "SHM not found. check __AFL_DIST_KV_SHM_ID"

    dist_kv = SharedDistKVStore.from_address(dist_shm_ptr_global)
    
    base_style = [
        {'selector': 'node', 'style': {'label': 'data(label)', 'color': 'white', 'background-color': '#007bff'}},
        {'selector': 'edge', 'style': {'label': 'data(label)', 'color': 'white', 'line-color': 'data(color)', 'target-arrow-shape': 'triangle', 'curve-style': 'bezier', 'width': 2}}
    ]

    status_elements = []
    
    for i in range(5):
        entry = dist_kv.entries[i]
        if entry.is_active:
            curr_bb = str(entry.last_bb_id)
            base_style.append({
                'selector': f'node[id = "{curr_bb}"]',
                'style': {'background-color': '#ffc107', 'width': '45px', 'height': '45px', 'border-width': '2px', 'border-color': 'white'}
            })
            
            status_elements.append(html.P([
                html.Span(f"Target {i}: ", style={'color': '#00ff00'}),
                html.Span(f"Dist {entry.min_distance} | BB {curr_bb}")
            ]))

    return base_style, status_elements

@app.callback(
    Output('node-data-display', 'children'),
    [Input('cfg-graph', 'tapNodeData')],
    [State('refresh-timer', 'n_intervals')]
)
def display_node_data(data, n):
    if not data or not dist_shm_ptr_global:
        return "Click a node to see if it's the current bottleneck seed."
    
    dist_kv = SharedDistKVStore.from_address(dist_shm_ptr_global)
    clicked_bb = data['id']
    
    for i in range(MAX_TARGETS):
        entry = dist_kv.entries[i]
        if entry.is_active and str(entry.last_bb_id) == clicked_bb:
            content = bytes(entry.seed_content[:entry.seed_len])
            return html.Div([
                html.P(f"Seed associated with BB {clicked_bb}:"),
                html.Code(content.hex(), style={'color': '#ff79c6'}),
                html.P(f"Seed in ASCII: {content.decode(errors='replace')}", style={'color': '#8be9fd'})
            ])
            
    return f"No active seed stopped at BB {clicked_bb} currently."

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8050, debug=False)