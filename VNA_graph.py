import numpy as np
from plotly.subplots import make_subplots
import plotly.graph_objects as go
import plotly.io as pio
import pandas as pd
import scipy.optimize as optimize
import colorsys
import argparse
import h5py
import skrf as rf
from pathlib import Path
import re

def get_graph_colors(n):
    """
    Generates n distinct colors transitioning from Red to Blue,
    optimized for a white background.
    """
    colors = []
    if n == 1:
        return [(200, 0, 0)]

    for i in range(n):
        hue = (i / (n - 1)) * 0.7
        lightness = 0.45
        saturation = 0.8
        rgb = colorsys.hls_to_rgb(hue, lightness, saturation)
        rgb_ints = tuple(int(val * 255) for val in rgb)
        colors.append(rgb_ints)
        
    return colors[::-1]

def extract_number(file): 
    filename = file.stem
    match = re.findall(r'-(-?\d*\.\d+|\d+)', filename)
    if match:
        return float(match[-1])
    return float('-inf')

# names = [
#     "151mK", #2026-03-13-13-01-39
#     "170mK", #2026-03-13-13-15-08
#     "204mK", #2026-03-13-13-27-52
#     "321mK", #2026-03-13-13-48-13
#     "526mK", #2026-03-13-14-04-35
#     "834mK", #2026-03-13-14-18-24
#     "983mK", #2026-03-13-14-23-50
#     "2K", #2026-03-13-15-14-54
#     "3.4K" #2026-03-13-15-21-33
# ]
    
base_path = Path("./2026-04-20")
folder_family = sorted(
    [f for f in base_path.iterdir() if f.is_dir()], 
    key=lambda x: x.name.lower()
)
    
count = 0
for count,j in enumerate(folder_family):
    name = j.name
    # name = name.split('_')[1]
    # name = name.replace(".",",")
    
    file_family = [f for f in j.iterdir()]

    file_family.sort(key=extract_number)

    fig = go.Figure()

    fig = make_subplots(
        rows=1, cols=1,
        shared_xaxes=False,
        vertical_spacing=0.05
    )

    done=None

    gather_freq =[]
    gather_magn =[]

    color = get_graph_colors(len(file_family))

    for count,i in enumerate(file_family):
        ntwk = rf.Network(i._raw_paths[0])
        freq = ntwk.f 
        val = ntwk.s_mag[:, 1, 0]

        calib = 1
        
        val = val * calib
        magn = np.abs(val)
        magn_dB = 20 * np.log10((np.abs(val)))
        
        gather_freq = freq
        gather_magn = magn_dB
        
        phase = np.angle(val)
        phase = np.unwrap(phase)
        x = np.arange(len(phase))
        m, q = np.polyfit(x, phase, 1)
        linear_phase = m * x + q
        phase -= linear_phase
        num_traces = len(file_family)
        
        #main graph
        fig.add_trace(go.Scattergl(
            x=gather_freq,
            y= gather_magn,
            legendgroup=f'{i.name}', # j for freq
            mode='lines',
            name=f'{i.name}',
            line=dict(color=f"rgb{color[count]}", width=1.5),
            opacity=0.7
        ),row=1,col=1)
    
    count +=1
    
    # height_val = 500 * len(filenames)

    height_val = 900

    if height_val <900:
        height_val=900
        
    fig.update_xaxes(title_text="Freq(Hz)", tickformat=".6s",ticksuffix="Hz", row=1, col=1)
    fig.update_yaxes(title_text="S21(dB)", row=1, col=1)

    fig.update_layout(
        height= height_val,
        title=f"{j.name}",
        template="ggplot2" # Often easier on the eyes for RF data
    )

    fig.write_html(f"./graph/{j.name}.html")
    fig.show()