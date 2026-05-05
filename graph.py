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


fig = go.Figure()

fig = make_subplots(
    rows=1, cols=1,
    shared_xaxes=False,
    vertical_spacing=0.05
)

ntwk = rf.Network('./data/force/Paris_MKID_2.0-2.1GHz_at_different_temperatures/')
freq = ntwk.f 
mag = ntwk.s_mag[:, 1, 0]
mag_db = ntwk.s_db[:, 1, 0] 
phase = ntwk.s_rad_unwrap[:, 1, 0]

phase = np.unwrap(phase)
x = np.arange(len(phase))
m, q = np.polyfit(x, phase, 1)
linear_phase = m * x + q
phase -= linear_phase

z = mag * np.exp(1j*phase)

re = np.real(z)
im = np.imag(z)

#main graph
fig.add_trace(go.Scattergl(
    x=freq,
    y=mag_db,
    mode='lines',
    name=f'yes',
    line=dict(color=f"black", width=1.5),
    opacity=0.7
),row=1,col=1)

height_val = 900

if height_val <900:
    height_val=900

fig.update_layout(
    height= height_val,
    title=f"yes",
    template="ggplot2" # Often easier on the eyes for RF data
)

fig.write_html(f"idk.html")
fig.show()