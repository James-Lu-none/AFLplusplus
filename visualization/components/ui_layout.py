from dash import html, dcc
import dash_cytoscape as cyto
from config import DEFAULT_REFRESH_INTERVAL, DEFAULT_TOP_N, MIN_REFRESH_INTERVAL, DEFAULT_CFG_ENABLED, DEFAULT_LLM_THRESHOLD, MIN_LLM_THRESHOLD, DEFAULT_LLM_ENDPOINT, DEFAULT_LLM_MODEL

def create_layout(initial_stylesheet):
    """
    Creates the main Dash layout.
    """
    return html.Div(
        style={'backgroundColor': '#121212', 'color': 'white', 'height': '100vh', 'padding': '10px', 'boxSizing': 'border-box', 'margin': '0', 'overflow': 'hidden'},
        children=[
            html.Div(style={'display': 'flex', 'gap': '15px', 'width': '100%', 'height': '100%', 'overflow': 'hidden'}, children=[
                # Graph visualization on the left
                html.Div(id='cfg-graph-container', style={'flex': '1 1 70%', 'minWidth': '0', 'display': 'flex', 'flexDirection': 'column'}, children=[
                    # Wrapper for the graph to make it resizable from the bottom
                    html.Div(
                        style={
                            'flex': '0 0 auto', 
                            'height': '70%', 
                            'minHeight': '100px', 
                            'resize': 'vertical', 
                            'overflow': 'hidden',
                            'borderBottom': '2px solid #444',
                            'paddingBottom': '2px'
                        },
                        children=[
                            cyto.Cytoscape(
                                id='cfg-graph',
                                elements=[],
                                autoungrabify=True,
                                autolock=True,
                                userZoomingEnabled=True,
                                userPanningEnabled=True,
                                layout={'name': 'preset'},
                                style={'width': '100%', 'height': '100%', 'border': 'none'},
                                stylesheet=initial_stylesheet
                            ),
                        ]
                    ),
                    # Log panel fills the rest and stays at bottom
                    html.Div(
                        id='log-panel', 
                        style={
                            'flex': '1', 
                            'backgroundColor': '#000', 
                            'color': '#00ff00', 
                            'fontFamily': 'monospace', 
                            'fontSize': '12px', 
                            'padding': '10px', 
                            'overflowY': 'auto', 
                            'border': '1px solid #444',
                            'borderTop': 'none',
                            'borderRadius': '0 0 5px 5px',
                            'whiteSpace': 'pre-wrap'
                        },
                        children="Monitoring started..."
                    )
                ]),
                
                # Live status and node info on the right
                html.Div(
                    style={
                        'flex': '0 0 30%', 
                        'minWidth': '350px',
                        'padding': '10px', 
                        'backgroundColor': '#1e1e1e', 
                        'display': 'flex', 
                        'flexDirection': 'column',
                        'overflowY': 'auto',
                        'maxHeight': '100%',
                        'border': '1px solid #444',
                        'borderRadius': '5px'
                    }, 
                    children=[
                        # refresh settings panel at the top
                        html.Div(
                            style={'padding': '10px', 'border': '1px solid #444', 'marginBottom': '10px'}, 
                            children=[
                                html.H4("Refresh Settings"),
                                html.Label("Refresh Interval (ms):", style={'fontSize': '12px'}),
                                dcc.Input(
                                    id='interval-setting',
                                    type='number',
                                    value=DEFAULT_REFRESH_INTERVAL,
                                    min=MIN_REFRESH_INTERVAL,
                                    step=1000,
                                    style={'backgroundColor': '#333', 'color': 'white', 'border': '1px solid #555', 'width': '100%'}
                                ),
                                html.Hr(),
                                html.Label("Filter Top N Nodes (Degree):", style={'fontSize': '12px'}),
                                dcc.Input(
                                    id='top-n-input',
                                    type='number',
                                    value=DEFAULT_TOP_N,
                                    min=0,
                                    step=1,
                                    style={'backgroundColor': '#333', 'color': 'white', 'border': '1px solid #555', 'width': '100%'}
                                ),
                                html.Hr(),
                                html.Label("LLM Feedback Threshold (sec):", style={'fontSize': '12px'}),
                                dcc.Input(
                                    id='llm-threshold-input',
                                    type='number',
                                    value=DEFAULT_LLM_THRESHOLD,
                                    min=MIN_LLM_THRESHOLD,
                                    step=1,
                                    style={'backgroundColor': '#333', 'color': 'white', 'border': '1px solid #555', 'width': '100%'}
                                ),
                                html.Hr(),
                                html.Label("LLM Endpoint:", style={'fontSize': '12px'}),
                                dcc.Input(
                                    id='llm-endpoint-input',
                                    type='text',
                                    value=DEFAULT_LLM_ENDPOINT,
                                    style={'backgroundColor': '#333', 'color': 'white', 'border': '1px solid #555', 'width': '100%'}
                                ),
                                html.Hr(),
                                html.Label("LLM Model:", style={'fontSize': '12px'}),
                                dcc.Input(
                                    id='llm-model-input',
                                    type='text',
                                    value=DEFAULT_LLM_MODEL,
                                    style={'backgroundColor': '#333', 'color': 'white', 'border': '1px solid #555', 'width': '100%'}
                                ),
                                html.Hr(),
                                html.Label("Visualization Settings", style={'fontSize': '12px'}),
                                dcc.Checklist(
                                    id='cfg-enabled-toggle',
                                    options=[{'label': ' Enable CFG Graph', 'value': 'enabled'}],
                                    value=['enabled'] if DEFAULT_CFG_ENABLED else [],
                                    style={'fontSize': '14px', 'marginTop': '5px'}
                                )
                            ]
                        ),

                        # clicked target info
                        html.Div(children=[
                            html.H4("Clicked Target Info"),
                            html.Div(
                                id='target-data-display', 
                                style={
                                    'wordBreak': 'break-all', 
                                    'fontFamily': 'monospace', 
                                    'fontSize': '12px', 
                                    'minHeight': '150px'
                                }
                            ),
                            html.Hr(),
                        ]),

                        # live status display
                        html.Div(children=[
                            html.H3("Live Status"),
                            html.Div(id='live-status-info'),
                            html.Hr(),
                        ]),
                        
                        # coverage heatmap visualization at the bottom
                        html.Div(style={'marginTop': 'auto'}, children=[
                            html.H4("Coverage Map"),
                            html.Div(
                                id='coverage-stats', 
                                style={'fontSize': '14px', 'color': '#00ff00', 'marginBottom': '5px'}
                            ),
                            dcc.Graph(
                                id='coverage-heatmap',
                                config={'displayModeBar': False},
                                style={'height': '300px'}
                            )
                        ])
                    ]
                )
            ]),
            
            dcc.Interval(id='refresh-timer', interval=DEFAULT_REFRESH_INTERVAL, n_intervals=0),
            dcc.Store(id='selected-target-idx', data=-1)
        ]
    )
