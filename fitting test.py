import numpy as np
from scipy.optimize import differential_evolution
import skrf as rf
from plotly.subplots import make_subplots
import plotly.graph_objects as go

def real_of_complex(z):
    '''
    Flatten n-dim complex vector to 2n-dim real vector for fitting.
    :param z: array of complex numbers.
    :return: an array composed by real and imaginary part of the number.
    '''
    r = np.hstack((z.real, z.imag))
    return r


def complex_of_real(r):
    '''
    Does the inverse of real_of_complex() function.
    :param r: real + imaginary data
    :return: array of complex numbers
    '''
    assert len(r.shape) == 1
    nt = r.size
    assert nt % 2 == 0
    no = int(nt / 2)
    z = r[:no] + 1j * r[no:]
    return z

def linear_model(f, f0, A, D, phi, Qc_re, Qc_im, Q):
    '''
    it wasNon-linear model for fitting resonators developed by Albert and Bryan.

    now it is linear

    :param f: Array containing frequency in Hz.         
    :param f0: Resonant frequency in Hz.                
    :param dQr: Inverse of Qr.
    :param dQc_re: Inverse of the real part of coupling quality factor.
    :param dQc_im: Inverse of the imaginary part of the coupling quality factor.
    :param a: Non-linear parameter.
    :return:
    '''    
    
    Qc = 1j*Qc_im + Qc_re
    
    cable_phase = np.exp(2j * np.pi * (1e-6 * D * (f - f0) + phi))
    
    s21 = A*cable_phase*(1 - (Q/Qc)/(1+2j*Q*(f-f0)/(f0)))

    return (np.real(s21),np.imag(s21))

ntwk = rf.Network("./data/fit_test/Lk1.s2p")
freq = ntwk.f 
freq = [f for f in freq if f<8e9]
s21_complex = ntwk.s[:len(freq), 1, 0] 
re_data = np.real(s21_complex)
im_data = np.imag(s21_complex)

# 2. Smart Bounds (Crucial for DE)
bounds = [
    (freq[0],freq[-1]), # f0
    (0.5, 1.5),               # A (assuming normalized)
    (-1, 1),                  # D 
    (-np.pi, np.pi),          # phi
    (100, 1e7),               # Qc_re
    (-1e5, 1e5),              # Qc_im
    (100, 1e7)                # Q
]

# 3. Objective (simplified)
def objective(params, x_data, complex_data):
    # Unpack params
    real_pred, imag_pred = linear_model(x_data, *params)
    z_pred = real_pred + 1j*imag_pred
    # Minimizing the squared distance in the complex plane
    return np.sum(np.abs(z_pred - complex_data))

result = differential_evolution(
    objective, 
    bounds, 
    args=(freq, s21_complex),
    popsize=15, # Increase if it still misses
    tol=0.01
)

# Your optimized parameters
best_params = result.x
print(f"Optimized Parameters: {best_params}")


pred_re, pred_im = linear_model(freq,*best_params)

pred = pred_re + 1j*pred_im

fig = go.Figure()

fig = make_subplots(
    rows=1, cols=1,
    shared_xaxes=False,
    vertical_spacing=0.02,
    subplot_titles="test fit"
)

fig.add_trace(go.Scattergl(
    x=freq,
    y=20*np.log10(np.abs(s21_complex)**2),
    mode='lines',
    name="orig",
    legendgroup=f'orig',
    line=dict(color='red', width=5),
    opacity=1
),row=1,col=1)

fig.add_trace(go.Scattergl(
    x=freq,
    y=20*np.log10(np.abs(pred)**2),
    mode='lines',
    name="pred",
    legendgroup=f'pred',
    line=dict(color='blue', width=2),
    opacity=1
),row=1,col=1)

fig.show()