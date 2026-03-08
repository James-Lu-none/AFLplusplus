from dash import html, dcc
import dash_cytoscape as cyto
from config import DEFAULT_REFRESH_INTERVAL, MIN_REFRESH_INTERVAL

def create_layout(cfg_elements, initial_stylesheet):
    """
    Creates the main Dash layout.
    """
    return html.Div(
        style={'backgroundColor': '#121212', 'color': 'white', 'height': '100vh', 'padding': '10px'},
        children=[
            html.H2("AFL++ LLM-Guided Fuzzing Monitor", style={'textAlign': 'center'}),
            
            html.Div(style={'display': 'flex'}, children=[
                # Graph visualization on the left
                html.Div(style={'width': '70%'}, children=[
                    cyto.Cytoscape(
                        id='cfg-graph',
                        elements=cfg_elements,
                        autoungrabify=True,
                        autolock=True,
                        userZoomingEnabled=True,
                        userPanningEnabled=True,
                        layout={'name': 'preset'},
                        style={'width': '100%', 'height': '750px', 'border': '1px solid #444'},
                        stylesheet=initial_stylesheet
                    )
                ]),
                
                # Live status and node info on the right
                html.Div(
                    style={
                        'width': '30%', 
                        'padding': '10px', 
                        'backgroundColor': '#1e1e1e', 
                        'marginLeft': '10px', 
                        'display': 'flex', 
                        'flexDirection': 'column'
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
                                    step=5000,
                                    style={'backgroundColor': '#333', 'color': 'white', 'border': '1px solid #555', 'width': '100%'}
                                ),
                                html.Hr(),
                                html.Label("Filter Top N Nodes (Degree):", style={'fontSize': '12px'}),
                                dcc.Input(
                                    id='top-n-input',
                                    type='number',
                                    value=0,
                                    min=0,
                                    step=1,
                                    style={'backgroundColor': '#333', 'color': 'white', 'border': '1px solid #555', 'width': '100%'}
                                )
                            ]
                        ),

                        # live status display
                        html.Div(children=[
                            html.H3("Live Status"),
                            html.Div(id='live-status-info'),
                            html.Hr(),
                            html.H4("Clicked Node Info"),
                            html.Div(
                                id='node-data-display', 
                                style={
                                    'wordBreak': 'break-all', 
                                    'fontFamily': 'monospace', 
                                    'fontSize': '12px', 
                                    'minHeight': '100px'
                                }
                            ),
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
            
            dcc.Interval(id='refresh-timer', interval=DEFAULT_REFRESH_INTERVAL, n_intervals=0)
        ]
    )
