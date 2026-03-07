import threading
import dash
from dash import html, dcc, Input, Output, State
import dash_cytoscape as cyto
import subprocess
import ctypes
import os
import re
import time
import numpy as np
import plotly.express as px
import plotly.graph_objects as go

MAX_TARGETS = 64
MAX_SEED_SIZE = 512

MAP_SIZE = 1048576 
GRID_DIM = 1024

COARSEN_FACTOR = 4
GRID_DIM_COARSE = GRID_DIM // COARSEN_FACTOR

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
coverageMap_shm_ptr_global = get_afl_shm_ptr("target_normal", "AFL_SHM_ID")

accumulated_map = np.zeros(MAP_SIZE, dtype=np.uint8)
map_lock = threading.Lock()

def shm_collector():
    global accumulated_map, coverageMap_shm_ptr_global
    print("SHM Collector Thread Started.")
    
    while True:
        if not coverageMap_shm_ptr_global:
            coverageMap_shm_ptr_global = get_afl_shm_ptr("target_normal", "AFL_SHM_ID")
        else:
            raw_bytes = ctypes.string_at(coverageMap_shm_ptr_global, MAP_SIZE)
            current_map = np.frombuffer(raw_bytes, dtype=np.uint8)
            with map_lock:
                np.maximum(accumulated_map, current_map, out=accumulated_map)
        time.sleep(0.001)


app.layout = html.Div(style={'backgroundColor': '#121212', 'color': 'white', 'height': '100vh', 'padding': '10px'}, children=[
    html.H2("AFL++ LLM-Guided Fuzzing Monitor", style={'textAlign': 'center'}),
    
    html.Div(style={'display': 'flex'}, children=[
        # Graph visualization on the left
        html.Div(style={'width': '70%'}, children=[
            cyto.Cytoscape(
                id='cfg-graph',
                elements=load_cfg_data("cfg_edges.txt"),
                layout={
                    'name': 'cose', 
                    'idealEdgeLength': 100,
                    'nodeOverlap': 20,
                    'refresh': 20,
                    'fit': True,
                    'padding': 30,
                    'randomize': False,
                    'componentSpacing': 100,
                    'nodeRepulsion': 400000,
                    'edgeElasticity': 100,
                },
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
        
        # Live status and node info on the right
        html.Div(style={'width': '30%', 'padding': '10px', 'backgroundColor': '#1e1e1e', 'marginLeft': '10px', 'display': 'flex', 'flexDirection': 'column'}, children=[
            # refresh settings panel at the top
            html.Div(style={'padding': '10px', 'border': '1px solid #444', 'marginBottom': '10px'}, children=[
                html.H4("Refresh Settings"),
                html.Label("Refresh Interval (ms):", style={'fontSize': '12px'}),
                dcc.Input(
                    id='interval-setting',
                    type='number',
                    value=10000,
                    min=5000,
                    step=5000,
                    style={'backgroundColor': '#333', 'color': 'white', 'border': '1px solid #555', 'width': '100%'}
                )
            ]),

            # live status display at the top
            html.Div(children=[
                html.H3("Live Status"),
                html.Div(id='live-status-info'),
                html.Hr(),
                html.H4("Clicked Node Info"),
                html.Div(id='node-data-display', style={'wordBreak': 'break-all', 'fontFamily': 'monospace', 'fontSize': '12px', 'minHeight': '100px'}),
            ]),
            
            # coverage heatmap visualization at the bottom
            html.Div(style={'marginTop': 'auto'}, children=[
                html.H4("Coverage Map"),
                html.Div(id='coverage-stats', style={'fontSize': '14px', 'color': '#00ff00', 'marginBottom': '5px'}),
                dcc.Graph(
                    id='coverage-heatmap',
                    config={'displayModeBar': False},
                    style={'height': '300px'}
                )
            ])
        ])
    ]),
    
    dcc.Interval(id='refresh-timer', interval=10000, n_intervals=0)
])

@app.callback(
    Output('refresh-timer', 'interval'),
    [Input('interval-setting', 'value')]
)
def update_refresh_rate(value):
    if value is None or value < 5000:
        return 1000
    return value

@app.callback(
    [Output('cfg-graph', 'stylesheet'),
     Output('live-status-info', 'children'),
     Output('coverage-heatmap', 'figure'),
     Output('coverage-stats', 'children')],
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
    # highlight top 5 targets with active seeds
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


    # draw coverage heatmap
    fig = go.Figure()

    with map_lock:
        map_1024_snapshot = accumulated_map.copy().reshape((GRID_DIM, GRID_DIM))
        hit_edges = np.count_nonzero(map_1024_snapshot)
        blocks = map_1024_snapshot.reshape(GRID_DIM_COARSE, COARSEN_FACTOR, GRID_DIM_COARSE, COARSEN_FACTOR)
        map_coarse_display = blocks.max(axis=(1, 3))
    density = (hit_edges / MAP_SIZE) * 100
    stats_text = f"Edges Hit: {hit_edges:,} | Density: {density:.6f}%"
    
    fig.add_trace(go.Heatmap(
        z=map_coarse_display,
        colorscale=[
            [0, 'rgb(0,0,0)'],
            [0.01, 'rgb(0, 255, 127)'],
            [1, 'rgb(255, 255, 255)']
        ],
        zmin=0,
        zmax=4, 
        showscale=False,
        hoverinfo='z'
    ))

    fig.update_layout(
        title=f"Coverage Map ({GRID_DIM_COARSE}x{GRID_DIM_COARSE} View, Enhanced)",
        margin=dict(l=0, r=0, b=0, t=30),
        xaxis={'visible': False},
        yaxis={'visible': False, 'autorange': 'reversed'},
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)'
    )

    return base_style, status_elements, fig, stats_text

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
    collector_thread = threading.Thread(target=shm_collector, daemon=True)
    collector_thread.start()
    
    app.run(host='0.0.0.0', port=8050, debug=False)