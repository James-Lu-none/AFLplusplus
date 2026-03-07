import numpy as np
import plotly.graph_objects as go
from config import GRID_DIM, GRID_DIM_COARSE, COARSEN_FACTOR, MAP_SIZE

def get_default_stylesheet():
    """
    Returns the basic stylesheet for Dash Cytoscape.
    """
    return [
        {'selector': 'node', 'style': {
            'label': 'data(label)', 
            'color': 'white', 
            'background-color': '#007bff'
        }},
        {'selector': 'edge', 'style': {
            'label': 'data(label)', 
            'line-color': 'data(color)', 
            'target-arrow-shape': 'triangle', 
            'curve-style': 'bezier',
            'font-size': '10px', 
            'color': '#aaa', 
            'width': 2
        }}
    ]

def generate_coverage_heatmap(accumulated_map, map_lock):
    """
    Generates a Plotly Heatmap figure for the coverage map.
    """
    fig = go.Figure()

    with map_lock:
        map_1024_snapshot = accumulated_map.copy().reshape((GRID_DIM, GRID_DIM))
        hit_edges = np.count_nonzero(map_1024_snapshot)
        # Reshape to aggregate by COARSEN_FACTOR
        blocks = map_1024_snapshot.reshape(GRID_DIM_COARSE, COARSEN_FACTOR, GRID_DIM_COARSE, COARSEN_FACTOR)
        map_coarse_display = blocks.max(axis=(1, 3))

    density = (hit_edges / MAP_SIZE) * 100
    stats_text = f"Edges Hit: {hit_edges:,} | Density: {density:.6f}%"
    
    fig.add_trace(go.Heatmap(
        z=map_coarse_display,
        colorscale=[
            [0, 'rgb(0,0,0)'],           # Not hit
            [0.01, 'rgb(0, 255, 127)'],  # Low hits
            [1, 'rgb(255, 255, 255)']    # High hits
        ],
        zmin=0,
        zmax=4, 
        showscale=False,
        hoverinfo='z'
    ))

    fig.update_layout(
        title=f"Coverage Map ({GRID_DIM_COARSE}x{GRID_DIM_COARSE} View)",
        margin=dict(l=0, r=0, b=0, t=30),
        xaxis={'visible': False},
        yaxis={'visible': False, 'autorange': 'reversed'},
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)'
    )

    return fig, stats_text
