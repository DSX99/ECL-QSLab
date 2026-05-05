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
from resonator_tools import circuit

def find_peaks(freq, magn, window_size=None, base_freq = 1e6, verbose = False):
    """
    Finds peaks in given data through window sliding with width of ... Hz, after that cheching by comparing the width of peaks
    Returns a 2d array marker_x,marker_y
    Args:
        freq (list): frequencies for data given in Hz
        magn (list): magnitude data, may be both in RMS and dB
        verbose (bool, optional): debug verbosity of function. Defaults to False.
    """
    #defining some constants

    #finds fluctuations at start and assumes them to be a universal noise level
    dB_threshhold=(np.max(magn[:100])-np.min(magn[:100]))
    if(verbose):
        print("assume noise threshold:",dB_threshhold)
    count=0
    possible_points=[]

    if window_size == None:
        window_size = int((freq[-1] - freq[0])/1e3)

    #windowed scan for peaks
    for i in range(0,len(magn),window_size):
        window = magn[i : i + window_size]

        min_window = min(window)
        min_index = np.where(window == min_window)[0][0]

        try:
            if ((((window[0]+window[1]+window[2]+window[3]+window[-1]+window[-2]+window[-3]+window[-4])/8) - min_window)>dB_threshhold ):
                possible_points.append(i + min_index)
                count+=1
        except IndexError:
            pass
        if(count>100):
            dB_threshhold+=dB_threshhold/3
            count=0
            if(verbose):
                print("too many possible points, restart with new dB_threshold:",dB_threshhold)
            possible_points=[]
            i=0

    if(verbose):
        print("estimation of peaks based on window search: ", freq[possible_points])

    #add verification of possible points // verification of no double dips (multiple dips in one window) (maybe just decrease window size for now)
        
    average_width=4
    shift =int(base_freq/(freq[1]-freq[0]))
    if(verbose):
        print("assuming base width of peak (indeces):",shift)
    marker_x=[]

    possible_points_tmp=[]
    for index in possible_points:
        if(index+shift+average_width+1>len(freq) or index-shift-average_width<0):
            if(verbose):
                print("discarding possible point due to being to close to edge on index: ", index," with freq: ", freq[index])
        else:    
            possible_points_tmp.append(index)

    possible_points = possible_points_tmp
    del possible_points_tmp

    possible_points_tmp = []

    for index in possible_points:
        window = magn[index - average_width : index + average_width + 1]
        window_shifted_neg = magn[index - shift - average_width : index - shift + average_width + 1]
        window_shifted_pos = magn[index + shift - average_width : index + shift + average_width + 1]
        if(((np.average(window_shifted_neg)+np.average(window_shifted_pos))/2) - np.average(window) > 2*dB_threshhold):
            possible_points_tmp.append(index)

    possible_points = possible_points_tmp
    del possible_points_tmp

    i=0
    while i < len(possible_points)-1:
        if (freq[possible_points[i+1]] - freq[possible_points[i]]) < (0.05 *1e9):
            if magn[possible_points[i]] < magn[possible_points[i+1]]:
                possible_points.pop(i+1)
            else:
                possible_points.pop(i)
            continue
        i+=1
        
        
    for i in possible_points:
        marker_x.append(freq[i])

    marker_y = magn[np.where(np.isin(freq,marker_x))]
    if(verbose):
        print("found ",len(marker_x), "peaks: ",marker_x)
    
    return marker_x,marker_y

"""_summary_
So first part of the code is copy of the caltech code with small changes purely for ease of use, then also fitter function

Main points:
    here everything works on rms
    many values were for some reason in MHz and noted as in MHz (even there where they werent)
    fwhm is written with assumptions on form, so its rewritten here
    fitting function rewritten for ease of use, well i guess mine use i dont know how easy it will be for others
"""

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


def fwhm(freq, magnitude):
    #changed
    mh = ((np.average(magnitude[0:4])+np.average(magnitude[-4:-1]))/2 + min(magnitude))/2
    freq_part = freq[magnitude < mh]    
    return (max(freq_part) - min(freq_part))





#non linear approx


def nonlinear_model(f, f0, A, phi, D, dQr, dQe_re, dQe_im, a):
    '''
    Non-linear model for fitting resonators developed by Albert and Bryan.

    :param f: Array containing frequency in Hz.         (changed from MHz to Hz)
    :param f0: Resonant frequency in Hz.                (changed from MHz to Hz)
    :param A: Amplitude of the resonator circle
    :param phi: phase of the resonator center
    :param D: Line delay of the line in ns?            !!!!!!!!!!! check it !!!!!!!!
    :param dQr: Inverse of Qr.
    :param dQe_re: Inverse of the real part of coupling quality factor.
    :param dQe_im: Inverse of the imaginary part of the coupling quality factor.
    :param a: Non-linear parameter.
    :return:
    '''
    cable_phase = np.exp(2.j * np.pi * (1e-6 * D * (f - f0) + phi))
    dQe = dQe_re + 1.j * dQe_im

    x0 = (f - f0) / f0
    y0 = x0 / dQr
    k2 = np.sqrt((y0 ** 3 / 27. + y0 / 12. + a / 8.) ** 2 - (y0 ** 2 / 9. - 1 / 12.) ** 3, dtype=np.complex128)
    k1 = np.power(a / 8. + y0 / 12. + k2 + y0 ** 3 / 27., 1. / 3)
    eps = (-1. + 3 ** 0.5 * 1j) / 2.

    y1 = y0 / 3. + (y0 ** 2 / 9. - 1 / 12.) / k1 + k1
    y2 = y0 / 3. + (y0 ** 2 / 9. - 1 / 12.) / eps / k1 + eps * k1
    y3 = y0 / 3. + (y0 ** 2 / 9. - 1 / 12.) / eps ** 2 / k1 + eps ** 2 * k1

    y1[np.abs(k1) == 0.0] = y0[np.abs(k1) == 0.0] / 3.
    y2[np.abs(k1) == 0.0] = y0[np.abs(k1) == 0.0] / 3.
    y3[np.abs(k1) == 0.0] = y0[np.abs(k1) == 0.0] / 3.

    # Out of the three roots we need to pick the right branch of the bifurcation
    thresh = 1e-4
    low_to_high = np.all(np.diff(f) > 0)
    if low_to_high:
        y = y2.real
        mask = (np.abs(y2.imag) >= thresh)
        y[mask] = y1.real[mask]
    else:
        y = y1.real
        mask = (np.abs(y1.imag) >= thresh)
        y[mask] = y2.real[mask]

    x = y * dQr

    s21 = A * cable_phase * (1. - (dQe) / (dQr + 2.j * x))

    return real_of_complex(s21)

def do_fit(freq, re, im, p0=None, f0=None):
    '''
    Function internally used to fit the resonators.
    This is not the function to call to fit a VNA scan, to do that, try vna_fit().
    Notes:
    * f0 in p0 is in Hz        (changed from MHz to Hz)
    '''
    model = nonlinear_model
    if p0 == None:
        mag = np.sqrt(re**2+im**2)
                
        fwhm_val = fwhm(freq,mag)
           
        i_m = np.mean([im[0], im[-1]])
        r_m = np.mean([re[0], re[-1]])
        p_m = np.arctan2(i_m, r_m)
        phi = p_m / (2 * np.pi)
        if(f0==None):
            f0 = freq[np.argmin(mag)]
        scale = np.max(mag)
        A = scale  # *np.cos(phi)
        D = 0  # m/(2.*np.pi)

        Qr = 10 * f0 / fwhm_val
        Qe_re = Qr * 2
        Qe_im = 0
        dQe = 1. / (1.j * Qe_im + Qe_re)
        a = 0.0
        p0 = (f0, A, phi, D, 1. / Qr, dQe.real, dQe.imag, a)
        
    pinit = p0

    ydata = np.hstack((re, im))
    
    popt, pcov = optimize.curve_fit(model, freq, ydata, p0=p0)  # ,bounds = (0,np.inf)

    f0, A, phi, D, dQr, dQe_re, dQe_im, a = popt

    yfit = model(freq, *popt)
    zfit = complex_of_real(yfit)

    zm = re + 1.j * im
    resid = zfit - zm
    Qr = 1 / dQr
    Qi = 1.0 / (dQr - dQe_re)

    dQe = dQe_re + 1.j * dQe_im
    Qe = 1. / dQe

    modelwise = (f0, A, phi, D, Qi, Qr, Qe.real, Qe.imag, a)

    return f0, Qi, Qe, Qr, zfit, popt, pcov, resid, pinit

def S21_func(f, f0, A, phi, D, dQr, dQe_re, dQe_im, a):
    '''
    Given a frequency range (f) and the resonator paramters return the S21 complex function.
    d<param name> is intended as 1./<param name>
    '''
    
    return complex_of_real(nonlinear_model(f, f0, A, phi, D, dQr, dQe_re, dQe_im, a))




#linear approx



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

    return real_of_complex(s21)



def do_fit_linear(freq, re, im, p0=None, f0=None):
    '''
    Function internally used to fit the resonators.
    This is not the function to call to fit a VNA scan, to do that, try vna_fit().
    Notes:
    * f0 in p0 is in Hz        (changed from MHz to Hz)
    '''
    model = linear_model
    if p0 == None:
        mag = np.sqrt(re**2+im**2)
                
        fwhm_val = fwhm(freq,mag)

        if(f0==None):
            f0 = freq[np.argmin(mag)]

        i_m = np.mean([im[0], im[-1]])
        r_m = np.mean([re[0], re[-1]])
        p_m = np.arctan2(i_m, r_m)
        phi = p_m / (2 * np.pi)
        D = 0

        A = (mag[0]+mag[-1]+mag[1]+mag[-2])/4
        Q = f0 / fwhm_val
        Qc_re = Q * 2
        Qc_im = 0
        p0 = (f0, A, D, phi, Qc_re, Qc_im, Q)

    pinit=p0

    ydata = np.hstack((re, im))
    
    z = re + 1j * im
    weights = 1.0 / np.abs(z - np.min(np.abs(z)) + 0.1)
    
    try:
        popt, pcov = optimize.curve_fit(model, freq, ydata, p0=p0, sigma=1/np.hstack((weights, weights)))  # ,bounds = (0,np.inf)
    except RuntimeError:
        popt = [1,1,1,1,1,1,1]
        pcov=[1,1,1]
        print("Not found optimal parameters")
        zm = re + 1j * im
        Qc = (1j * Qc_im + Qc_re)
        Qi = 1.0 / (1/Q - 1/Qc)
        yfit = model(freq, *popt)
        zfit = complex_of_real(yfit)
        resid = zm - zfit
        return f0, Qi, Qc, Q, zfit, popt, pcov, resid, pinit
    
    f0, A, D, phi, Qc_re, Qc_im, Q = popt

    Qc = (1j * Qc_im + Qc_re)

    yfit = model(freq, *popt)
    zfit = complex_of_real(yfit)

    zm = re + 1j * im
    resid = zm - zfit
    
    Qi = 1.0 / (1/Q - 1/Qc)

    return f0, Qi, Qc, Q, zfit, popt, pcov, resid, pinit

def S21_func_linear(f, f0, A, D, phi, Qc_re, Qc_im, Q):
    '''
    Given a frequency range (f) and the resonator paramters return the S21 complex function.
    d<param name> is intended as 1./<param name>
    '''
    return complex_of_real(linear_model(f, f0, A, D, phi, Qc_re, Qc_im, Q))



if __name__ == "__main__":
    
    base_path = Path("./data/fit_test")
    files = [f for f in base_path.iterdir()]
    file_names = [f.name for f in files]
    
    file_names.sort()
    order_map = {name: i for i, name in enumerate(file_names)}
    files.sort(key=lambda f: order_map.get(f.name))

    fig = go.Figure()

    fig = make_subplots(
        rows=3*len(files), cols=1,
        shared_xaxes=False,
        vertical_spacing=0.02,
        subplot_titles=file_names+file_names
    )
    
    out=[]
    
    for index, file in enumerate(files, start=1):
        ntwk = rf.Network(file)
        freq = ntwk.f
        mag = ntwk.s_mag[:, 1, 0]
        magn_dB = ntwk.s_db[:, 1, 0] 
        phase = ntwk.s_rad_unwrap[:, 1, 0]
        freq = [f for f in freq if f <8e9]
        freq = np.array(freq)
        mag = mag[:len(freq)]
        magn_dB = magn_dB[:len(freq)]
        phase = phase[:len(freq)]
        x = np.arange(len(phase))
        m, q = np.polyfit(x, phase, 1)
        phase = phase - (m * x + q)
            
        fig.add_trace(go.Scattergl(
            x=freq,
            y= magn_dB,
            legendgroup=f'raw {file.name}',
            mode='lines',
            name=f"raw {file.name}",
            line=dict(color='black', width=1.5),
            opacity=0.7
        ),row=index,col=1)
        
        fig.update_xaxes(title_text="Freq", tickformat=".7s",ticksuffix="Hz", row=index, col=1)
        fig.update_yaxes(title_text="S21(dB)", row=index, col=1)
        
        marker_x, marker_y = find_peaks(freq,magn_dB ,window_size= 100 ,base_freq=2e8, verbose=0)
        
        fig.add_trace(go.Scattergl(
            x=marker_x,
            y=marker_y,
            mode='markers',
            name=f"resonator guesses for {file.name}",
            marker=dict(
                color='red',
                size=8,
                symbol='diamond',
                line=dict(width=2, color='White')
            )
        ),row=index,col=1)
        
        point_indexes = np.where(np.isin(freq,marker_x))[0]
        num_traces = len(marker_x)
        
        for count,point in enumerate(point_indexes, start=1):
            
            point_high = np.abs(freq - (freq[point]+1e6)).argmin()
            point_low = np.abs(freq - (freq[point]-1e6)).argmin()
            
            freq_tmp = freq[point_low:point_high]
            phase_temp = phase[point_low:point_high]

            s21 = mag*np.exp(1j*phase)

            re = np.real(s21[point_low:point_high])
            im = np.imag(s21[point_low:point_high])
            
            fig.add_trace(go.Scattergl(
                x=re,
                y=im,
                legendgroup=f'raw circle {file.name} {count}',
                mode='lines',
                name=f"raw circle {file.name} {count}",
                line=dict(color='black', width=1.5),
                opacity=0.7
            ),row=2*len(files)+index,col=1)
            
            re_mark = np.abs(mag[point]) * np.cos(phase[point])
            im_mark = np.abs(mag[point]) * np.sin(phase[point])
            fig.add_trace(go.Scattergl(
                x=[re_mark],
                y=[im_mark],
                mode='markers',
                name=f"marker circle {file.name} {count}",
                marker=dict(
                    color='red',
                    size=6,
                    symbol='diamond',
                    line=dict(width=2, color='White')
                )
            ),row=2*len(files)+index,col=1)
                
            f0, Qi, Qe, Qr, zfit, popt, pcov, resid, pinit = do_fit_linear(freq_tmp,re,im,f0=freq_tmp[int(len(freq_tmp)/2)])
            
            fit = S21_func_linear(freq_tmp,*popt)
            
            hue = (count - 1) * (180 / max(1, num_traces - 1)) 
            # Convert HSL to RGB (Saturation 0.8, Lightness 0.5 for vibrant colors)
            rgb = colorsys.hls_to_rgb(hue / 360, 0.5, 0.8)
            
            legend_label = (
                f"<b><span style='font-size: 16px'>Fit {count} for {file.name}</span></b><br>"
                f"f0:  {f0}<br>"
                f"Q: {Qr}<br>"
                f"Q_c: {Qe}<br>"
                f"Q_i: {Qi}<br>"
            )
            
            out+=f"{file.name}: \nf0={f0}\nQ={Qr}\nQ_c={Qe}\nQ_i={Qi}\n"

            fig.add_trace(go.Scattergl(
                    x=freq_tmp,
                    y=20*np.log10(np.abs(fit)),
                    mode='lines',
                    name=legend_label,
                    legendgroup=f'fit {count} {file.name}',
                    line=dict(color=f'rgb({int(rgb[0]*255)}, {int(rgb[1]*255)}, {int(rgb[2]*255)})', width=1.5),
                    opacity=1
                ),row=index,col=1)
            
            fig.add_trace(go.Scattergl(
                    x=freq_tmp,
                    y=phase_temp,
                    mode='lines',
                    name=f'phase {count} {file.name}',
                    legendgroup=f'phase {count} {file.name}',
                    line=dict(color=f'black', width=1.5),
                    opacity=1
                ),row=len(file_names)+index,col=1)
            
            fig.add_trace(go.Scattergl(
                    x=freq_tmp,
                    y=np.angle(fit),
                    mode='lines',
                    name=f'phase fit {count} {file.name}',
                    legendgroup=f'phase fit {count} {file.name}',
                    line=dict(color=f'red', width=1.5),
                    opacity=1
                ),row=len(file_names)+index,col=1)
            
            fig.add_trace(go.Scattergl(
                    x=freq_tmp,
                    y=20* np.log10((np.abs(S21_func_linear(freq_tmp,*pinit)))),
                    mode='lines',
                    name=f'initial guess:{count} {file.name}',
                    legendgroup=f'{index}_initial',
                    line=dict(color=f'rgb({int(rgb[0]*128)}, {int(rgb[1]*128)}, {int(rgb[2]*128)})', width=1.5),
                    opacity=1
                ),row=index,col=1)   
            
            IQ = fit
            I=IQ.real
            Q=IQ.imag
            fig.add_trace(go.Scattergl(
                x=I,
                y=Q,
                legendgroup=f'opt circle {file.name} {count}',
                mode='lines',
                name=f"opt circle {file.name} {count}",
                line=dict(color=f'rgb({int(rgb[0]*255)}, {int(rgb[1]*255)}, {int(rgb[2]*255)})', width=1.5),
                opacity=0.7
            ),row=2*len(files)+index,col=1) 
            
            fig.update_yaxes(
                scaleanchor=f"x{2*len(files)+index}",
                scaleratio=1,
                row=2*len(files)+index, col=1
            )
            fig.update_xaxes(title_text="Real (I)", row=2*len(files)+index, col=1)
            fig.update_yaxes(title_text="Imag (Q)", row=2*len(files)+index, col=1)

    height_val = 1000 * len(files)

    if height_val <900:
        height_val=900

    fig.update_layout(
        height= height_val,
        title=f"Fitting test",
        template="ggplot2" # Often easier on the eyes for RF data
    )

    print("".join(out))
    
    fig.show()   
    fig.write_html(f"fitting_test.html")
        
        