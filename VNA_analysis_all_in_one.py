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

"""
    Define all of you files in filenames, do it as a relative path (see example)
"""
filenames=[
    "./auto_2/2026-03-13-13-01-39/1.9ghz-2.0ghz.s2p",
    "./auto_2/2026-03-13-13-01-39/2.0ghz-2.1ghz.s2p",
    "./auto_2/2026-03-13-13-01-39/2.1ghz-2.2ghz.s2p",
    "./auto_2/2026-03-13-13-01-39/2.2ghz-2.3ghz.s2p",
    "./auto_2/2026-03-13-13-01-39/2.3ghz-2.4ghz.s2p",
    "./auto_2/2026-03-13-13-01-39/2.4ghz-2.5ghz.s2p",
    "./auto_2/2026-03-13-14-18-24/1.9ghz-2.0ghz.s2p",
    "./auto_2/2026-03-13-14-18-24/2.0ghz-2.1ghz.s2p",
    "./auto_2/2026-03-13-14-18-24/2.1ghz-2.2ghz.s2p",
    "./auto_2/2026-03-13-14-18-24/2.2ghz-2.3ghz.s2p",
    "./auto_2/2026-03-13-14-18-24/2.3ghz-2.4ghz.s2p",
    "./auto_2/2026-03-13-14-18-24/2.4ghz-2.5ghz.s2p",    
    "./auto_2/2026-03-13-15-21-33/1.9ghz-2.0ghz.s2p",
    "./auto_2/2026-03-13-15-21-33/2.0ghz-2.1ghz.s2p",
    "./auto_2/2026-03-13-15-21-33/2.1ghz-2.2ghz.s2p",
    "./auto_2/2026-03-13-15-21-33/2.2ghz-2.3ghz.s2p",
    "./auto_2/2026-03-13-15-21-33/2.3ghz-2.4ghz.s2p",
    "./auto_2/2026-03-13-15-21-33/2.4ghz-2.5ghz.s2p"
]

names =[
    "151mK",
    "834mK",
    "3.4K"
]

filenames_2=[
    "./auto_2/2026-03-13-13-01-39/2.0ghz-2.1ghz.s2p",
    "./auto_2/2026-03-13-13-15-08/2.0ghz-2.1ghz.s2p",
    "./auto_2/2026-03-13-13-27-52/2.0ghz-2.1ghz.s2p",
    "./auto_2/2026-03-13-13-48-13/2.0ghz-2.1ghz.s2p",
    "./auto_2/2026-03-13-14-04-35/2.0ghz-2.1ghz.s2p",
    "./auto_2/2026-03-13-14-18-24/2.0ghz-2.1ghz.s2p",
    "./auto_2/2026-03-13-14-23-50/2.0ghz-2.1ghz.s2p",
    "./auto_2/2026-03-13-15-14-54/2.0ghz-2.1ghz.s2p",
    "./auto_2/2026-03-13-15-21-33/2.0ghz-2.1ghz.s2p",
]

names_2 = [
    "151mK", #2026-03-13-13-01-39
    "170mK", #2026-03-13-13-15-08
    "204mK", #2026-03-13-13-27-52
    "321mK", #2026-03-13-13-48-13
    "526mK", #2026-03-13-14-04-35
    "834mK", #2026-03-13-14-18-24
    "983mK", #2026-03-13-14-23-50
    "2K", #2026-03-13-15-14-54
    "3.4K" #2026-03-13-15-21-33
]

# filenames = [
#     "./auto_2/Ch1_20260320_16-01-33.s2p"
# ]

# names = [
#     "1"
# ]

# filenames = [
#     "./auto/2.01-2.11Ghz.s2p",
#     "./auto/2.01-2.11Ghz_BASE.s2p"
# ]

# filenames = [
#     "./20001points/1.8-1.9ghz.s2p",
#     "./20001points/1.9-2ghz.s2p",
#     "./20001points/2-2.1ghz.s2p",
#     "./20001points/2.1-2.2ghz.s2p",
#     "./20001points/2.2-2.3ghz.s2p",
#     "./20001points/2.3-2.4ghz.s2p",
#     "./20001points/2.4-2.5ghz.s2p"
# ]










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
        if (freq[possible_points[i+1]] - freq[possible_points[i]]) < (0.0005 *1e9):
            if magn[possible_points[i]] < magn[possible_points[i+1]]:
                possible_points.pop(i+1)
            else:
                possible_points.pop(i)
            continue
        i+=1
        
        
    for i in possible_points:
        marker_x.append(freq[i])

    marker_y = magn[np.where(np.isin(freq,marker_x))]
    
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
    Non-linear model for fitting resonators developed by Albert and Bryan.

    :param f: Array containing frequency in Hz.         
    :param f0: Resonant frequency in Hz.                
    :param dQr: Inverse of Qr.
    :param dQc_re: Inverse of the real part of coupling quality factor.
    :param dQc_im: Inverse of the imaginary part of the coupling quality factor.
    :param a: Non-linear parameter.
    :return:
    '''    
    
    Qc = 1j*Qc_im + Qc_re
    
    cable_phase = np.exp(2.j * np.pi * (1e-6 * D * (f - f0) + phi))
    
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
        Q = 10 * f0 / fwhm_val
        Qc_re = Q * 2
        Qc_im = 0
        p0 = (f0, A, D, phi, Qc_re, Qc_im, Q)

    pinit=p0

    ydata = np.hstack((re, im))
    
    try:
        popt, pcov = optimize.curve_fit(model, freq, ydata, p0=p0)  # ,bounds = (0,np.inf)
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
    pio.renderers.default = "browser"

    parser = argparse.ArgumentParser(description="Analysis of VNA data both h5 and csv")
    parser.add_argument("-i", "--initial", type=int, required=False, default=0, const=1, nargs='?')
    parser.add_argument('-v',"--verbose", type=int, nargs='?', const=1, default=0, required=False)
    parser.add_argument("-w", "--write", type=str, default=None, help="write to html with this name")
    parser.add_argument("-s", "--s2p", type=int, required=False, default=0, const=1, nargs="?", help="import data as s2p")
    parser.add_argument("--h5", type=int, required=False, default=0, const=1, nargs="?", help="import data as h5")
    parser.add_argument("-d", "--diff", type=int, required=False, default=0, const=1, nargs="?", help="work on diff of odd on even (1st on 2nd, 3rd on 4th)")
    
    args = parser.parse_args()
    
    verbose = args.verbose
    
    # magn = 10 * np.log10(20 * (np.abs(val)) ** 2) //rms to db
    # magn = np.sqrt(10**(val/10)/20) //db to rms

    #reading as csv
    # df = pd.read_csv('./vna_cleaned_data.csv')
    # freq = df.iloc[:, 0].values
    # magn = df.iloc[:, 1].values
    # phase = df.iloc[:, 2].values
    
    fig = go.Figure()
    if(not args.diff):
        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=False,
            vertical_spacing=0.05,
            subplot_titles=["1.9 Ghz - 2.5 Ghz for different temperatures","2.0 Ghz - 2.1 Ghz for differnet temperatures"]
        )
    else:
        fig = make_subplots(
            rows=2*len(filenames), cols=1,
            shared_xaxes=True,
            vertical_spacing=0.05,
            subplot_titles=filenames
        )
        
    row_count=1
    
    done=None
    
    if(args.h5):

        paths = [
            'VNA_0/S21',
            'VNA_0/frequency'
        ]
        for i in filenames:
            with h5py.File(i, 'r') as f:
                arrays = [f[p][:] for p in paths]
                calib = f['VNA_0'].attrs['calibration']

                val, freq = arrays
                
                val = val[0:-25]
                freq = freq[0:-25]
                
                val = val * calib
                magn = np.abs(val)
                magn_dB = 10 * np.log10(20 * (np.abs(val)) ** 2)
                
                #angle fixing (unwraps(no jumps over pi)), also deletes linear rise element
                phase = np.angle(val)
                phase = np.unwrap(phase)
                x = np.arange(len(phase))
                m, q = np.polyfit(x, phase, 1)
                linear_phase = m * x + q
                phase -= linear_phase

                marker_x , marker_y = find_peaks(freq, magn, verbose)
                marker_y = 10 * np.log10(20 * (np.abs(marker_y)) ** 2)


                if freq[-1]-freq[0]<1e7:
                    marker_x = [marker_x[np.argmin(marker_y)]]    
                    marker_y = [marker_y[np.argmin(marker_y)]]

                #main graph
                fig.add_trace(go.Scattergl(
                    x=freq,
                    y= magn_dB,
                    legendgroup='magnitude',
                    mode='lines',
                    name="<b><span style='font-size: 16px'> Data </span></b><br>",
                    line=dict(color='blue', width=1),
                    opacity=0.7
                ),row=row_count,col=1)

                #markers
                fig.add_trace(go.Scattergl(
                    x=marker_x,
                    y=marker_y,
                    mode='markers',
                    name="<b><span style='font-size: 16px'> Initial guess markers (aka minimal points) </span></b><br>",
                    marker=dict(
                        color='red',
                        size=12,
                        symbol='diamond',
                        line=dict(width=2, color='White')
                    )
                ),row=row_count,col=1)

                point_indexes = np.where(np.isin(freq,marker_x))[0]

                #can be calculated on each point later
                if(freq[-1]-freq[0]>1e7):
                    width = 1000
                else:
                    do_not_wide=1

                num_traces = len(point_indexes)

                for count,point in enumerate(point_indexes, start=1):
                    if(do_not_wide):
                        freq_tmp = freq
                    else:
                        freq_tmp = freq[point-width:point+width]

                    if(do_not_wide):
                        re = np.abs(val) * np.cos(phase)
                        im = np.abs(val) * np.sin(phase)
                    else:
                        re = np.abs(val[point-width:point+width]) * np.cos(phase)
                        im = np.abs(val[point-width:point+width]) * np.sin(phase)
                    
                    f0, Qi, Qe, Qr, zfit, popt, pcov, resid, pinit = do_fit_linear(freq_tmp,re,im,f0=freq_tmp[int(len(freq_tmp)/2)])
                    
                    zfit = 10 * np.log10(20 * (np.abs(zfit)) ** 2)
                    
                    hue = (count - 1) * (180 / max(1, num_traces - 1)) 
                    # Convert HSL to RGB (Saturation 0.8, Lightness 0.5 for vibrant colors)
                    rgb = colorsys.hls_to_rgb(hue / 360, 0.5, 0.8)
                    
                    legend_label = (
                        f"<b><span style='font-size: 16px'>Fit {count}</span></b><br>"
                        f"f0:  {f0}<br>"
                        f"Q_r: {Qr}<br>"
                        f"Q_e: {Qe}<br>"
                        f"Q_i: {Qi}<br>"
                    )

                    print(f"{count} pcov:{pcov}")
                    
                    #fit
                    #mag
                    fig.add_trace(go.Scattergl(
                        x=freq_tmp,
                        y=zfit,
                        mode='lines',
                        name=legend_label,
                        legendgroup=f'{count}',
                        line=dict(color=f'rgb({int(rgb[0]*255)}, {int(rgb[1]*255)}, {int(rgb[2]*255)})', width=1.5),
                        opacity=1
                    ),row=row_count,col=1)
                    
                    fig.add_trace(go.Scattergl(
                        x=[f0],
                        y=[zfit[np.abs(freq_tmp-f0).argmin()]],
                        mode='markers',
                        name=legend_label,
                        legendgroup=f'{count}',
                        showlegend=False,
                        line=dict(color=f'rgb({int(rgb[0]*255)}, {int(rgb[1]*255)}, {int(rgb[2]*255)})', width=1.5),
                        opacity=1
                    ),row=row_count,col=1)

                    if(args.initial):    
                        fig.add_trace(go.Scattergl(
                            x=freq_tmp,
                            y=10 * np.log10(20 * (np.abs(S21_func_linear(freq_tmp,*pinit))) ** 2),
                            mode='lines',
                            name=f'initial guess:{count}',
                            legendgroup=f'{count}_initial',
                            line=dict(color=f'rgb({int(rgb[0]*128)}, {int(rgb[1]*128)}, {int(rgb[2]*128)})', width=1.5),
                            opacity=1
                        ),row=row_count,col=1)    
                        
                    row_count+=1        

    elif(args.s2p):
        if(not args.diff):
            count = 0
            for i in filenames:
                ntwk = rf.Network(i)
                freq = ntwk.f 
                val = ntwk.s_mag[:, 1, 0]
                
                # val = val[0:-25]
                # freq = freq[0:-25]
                
                #assume calibrated VNA (idk if it even gives calib)
                calib = 1
                
                val = val * calib
                magn = np.abs(val)
                magn_dB = 10 * np.log10(20 * (np.abs(val)) ** 2)
                
                #angle fixing (unwraps(no jumps over pi)), also deletes linear rise element
                phase = np.angle(val)
                phase = np.unwrap(phase)
                x = np.arange(len(phase))
                m, q = np.polyfit(x, phase, 1)
                linear_phase = m * x + q
                phase -= linear_phase

                # marker_x , marker_y = find_peaks(freq, magn, verbose = verbose, window_size= 30,base_freq=2e5)
                # marker_y = 10 * np.log10(20 * (np.abs(marker_y)) ** 2)


                # if freq[-1]-freq[0]<1e7:
                #     marker_x = [marker_x[np.argmin(marker_y)]]    
                #     marker_y = [marker_y[np.argmin(marker_y)]]

                num_traces = len(filenames)

                hue = (count//6 - 1) * (90 / max(1, num_traces//6 - 1)) 
                # Convert HSL to RGB (Saturation 0.8, Lightness 0.5 for vibrant colors)
                rgb = colorsys.hls_to_rgb(hue / 360, 0.5, 0.8)


                color = ['rgb(204, 121, 167)','rgb(230, 159, 0)','rgb(86, 180, 233)']

                name = ""
                if(done!=(count//6)):
                    name=f"<b><span style='font-size: 16px'> {names[count//6]} </span></b><br>"
                    done=count//6

                #main graph
                fig.add_trace(go.Scattergl(
                    x=freq,
                    y= magn_dB,
                    legendgroup=f'{names[count//6]}',
                    mode='lines',
                    name=name,
                    line=dict(color=color[count//6], width=1.5),
                    opacity=0.7
                ),row=row_count,col=1)
                
                count +=1

                # #markers
                # fig.add_trace(go.Scattergl(
                #     x=marker_x,
                #     y=marker_y,
                #     mode='markers',
                #     name="<b><span style='font-size: 16px'> Initial guess markers (aka minimal points) </span></b><br>",
                #     marker=dict(
                #         color='red',
                #         size=12,
                #         symbol='diamond',
                #         line=dict(width=2, color='White')
                #     )
                # ),row=row_count,col=1)

                # point_indexes = np.where(np.isin(freq,marker_x))[0]

                # #can be calculated on each point later
                # if(freq[-1]-freq[0]>1e7):
                #     width = 50
                #     do_not_wide=0
                # else:
                #     do_not_wide=1

                # num_traces = len(point_indexes)

                # for count,point in enumerate(point_indexes, start=1):
                #     if(do_not_wide):
                #         freq_tmp = freq
                #         phase_temp = phase
                #     else:
                #         freq_tmp = freq[point-width:point+width]
                #         phase_temp = phase[point-width:point+width]

                #     if(do_not_wide):
                #         re = np.abs(val) * np.cos(phase)
                #         im = np.abs(val) * np.sin(phase)
                #     else:
                #         re = np.abs(val[point-width:point+width]) * np.cos(phase_temp)
                #         im = np.abs(val[point-width:point+width]) * np.sin(phase_temp)
                    
                #     f0, Qi, Qe, Qr, zfit, popt, pcov, resid, pinit = do_fit_linear(freq_tmp,re,im,f0=freq_tmp[int(len(freq_tmp)/2)])
                    
                #     zfit = 10 * np.log10(20 * (np.abs(zfit)) ** 2)
                    
                #     hue = (count - 1) * (180 / max(1, num_traces - 1)) 
                #     # Convert HSL to RGB (Saturation 0.8, Lightness 0.5 for vibrant colors)
                #     rgb = colorsys.hls_to_rgb(hue / 360, 0.5, 0.8)
                    
                #     legend_label = (
                #         f"<b><span style='font-size: 16px'>Fit {count}</span></b><br>"
                #         f"f0:  {f0}<br>"
                #         f"Q_r: {Qr}<br>"
                #         f"Q_e: {Qe}<br>"
                #         f"Q_i: {Qi}<br>"
                #     )

                #     if(verbose):
                #         print(f"{count} pcov:{pcov}")
                    
                #     #fit
                #     #mag
                #     fig.add_trace(go.Scattergl(
                #         x=freq_tmp,
                #         y=zfit,
                #         mode='lines',
                #         name=legend_label,
                #         legendgroup=f'{count}',
                #         line=dict(color=f'rgb({int(rgb[0]*255)}, {int(rgb[1]*255)}, {int(rgb[2]*255)})', width=1.5),
                #         opacity=1
                #     ),row=row_count,col=1)
                    
                #     fig.add_trace(go.Scattergl(
                #         x=[f0],
                #         y=[zfit[np.abs(freq_tmp-f0).argmin()]],
                #         mode='markers',
                #         name=legend_label,
                #         legendgroup=f'{count}',
                #         showlegend=False,
                #         line=dict(color=f'rgb({int(rgb[0]*255)}, {int(rgb[1]*255)}, {int(rgb[2]*255)})', width=1.5),
                #         opacity=1
                #     ),row=row_count,col=1)

                #     if(args.initial):    
                #         fig.add_trace(go.Scattergl(
                #             x=freq_tmp,
                #             y=10 * np.log10(20 * (np.abs(S21_func_linear(freq_tmp,*pinit))) ** 2),
                #             mode='lines',
                #             name=f'initial guess:{count}',
                #             legendgroup=f'{count}_initial',
                #             line=dict(color=f'rgb({int(rgb[0]*128)}, {int(rgb[1]*128)}, {int(rgb[2]*128)})', width=1.5),
                #             opacity=1
                #         ),row=row_count,col=1)    
                        
                # row_count+=1  
            count=0
            row_count+=1
            for i in filenames_2:
                ntwk = rf.Network(i)
                freq = ntwk.f 
                val = ntwk.s_mag[:, 1, 0]
                
                # val = val[0:-25]
                # freq = freq[0:-25]
                
                #assume calibrated VNA (idk if it even gives calib)
                calib = 1
                
                val = val * calib
                magn = np.abs(val)
                magn_dB = 10 * np.log10(20 * (np.abs(val)) ** 2)
                
                #angle fixing (unwraps(no jumps over pi)), also deletes linear rise element
                phase = np.angle(val)
                phase = np.unwrap(phase)
                x = np.arange(len(phase))
                m, q = np.polyfit(x, phase, 1)
                linear_phase = m * x + q
                phase -= linear_phase

                # marker_x , marker_y = find_peaks(freq, magn, verbose = verbose, window_size= 30,base_freq=2e5)
                # marker_y = 10 * np.log10(20 * (np.abs(marker_y)) ** 2)


                # if freq[-1]-freq[0]<1e7:
                #     marker_x = [marker_x[np.argmin(marker_y)]]    
                #     marker_y = [marker_y[np.argmin(marker_y)]]

                num_traces = len(filenames_2)

                hue = (count//6 - 1) * (90 / max(1, num_traces//6 - 1)) 
                # Convert HSL to RGB (Saturation 0.8, Lightness 0.5 for vibrant colors)
                rgb = colorsys.hls_to_rgb(hue / 360, 0.5, 0.8)


                color = [
                    "rgb(0, 0, 0)",         # Black
                    "rgb(230, 159, 0)",     # Orange
                    "rgb(86, 180, 233)",    # Sky Blue
                    "rgb(0, 158, 115)",     # Bluish Green
                    "rgb(240, 228, 66)",    # Yellow
                    "rgb(0, 114, 178)",     # Blue
                    "rgb(213, 94, 0)",      # Vermillion
                    "rgb(204, 121, 167)",   # Reddish Purple
                    "rgb(153, 153, 153)"    # Grey
                ]
                
                name = None
                if(done!=(count)):
                    name=f"<b><span style='font-size: 16px'> {names_2[count]} </span></b><br>"
                    done=count

                #main graph
                fig.add_trace(go.Scattergl(
                    x=freq,
                    y= magn_dB,
                    legendgroup=f'{names_2[count]}',
                    mode='lines',
                    name=name,
                    line=dict(color=color[count], width=1.5),
                    opacity=0.7
                ),row=row_count,col=1)
                
                count +=1
        else:
            count=0
            for i in range(0,len(filenames),2):
                ntwk1 = rf.Network(filenames[i])
                freq_1 = ntwk1.f 
                val_1 = ntwk1.s_mag[:, 1, 0]    
                
                mag_db_1 = 10 * np.log10(20 * (np.abs(val_1)) ** 2)
                
                ntwk2 = rf.Network(filenames[i+1])
                freq_2 = ntwk2.f 
                val_2 = ntwk2.s_mag[:, 1, 0]    
                
                mag_db_2 = 10 * np.log10(20 * (np.abs(val_2)) ** 2)

                fig.add_trace(go.Scattergl(
                    x=freq_1,
                    y=mag_db_1,
                    mode='lines',
                    name=f'{filenames[i]}',
                    line=dict(color='red', width=2),
                    opacity=0.7
                ),row=2*count+1,col=1)
                
                fig.add_trace(go.Scattergl(
                    x=freq_2,
                    y=mag_db_2,
                    mode='lines',
                    name=f'{filenames[i+1]}',
                    line=dict(color='blue', width=2),
                    opacity=0.7
                ),row=2*count+1,col=1)
                
                val = val_2-val_1
                freq=freq_1
                # mag_db = 10 * np.log10(20 * (np.abs(val)) ** 2)
                # freq= freq_1
                
                # fig.add_trace(go.Scattergl(
                #     x=freq,
                #     y=mag_db,
                #     mode='lines',
                #     name=f'{filenames[i+1]}',
                #     line=dict(color='blue', width=2),
                #     opacity=0.7
                # ),row=2*count+2,col=1)
                
                # magn = np.abs(val)
                # magn_dB = 10 * np.log10(20 * (np.abs(val)) ** 2)
                
                # #angle fixing (unwraps(no jumps over pi)), also deletes linear rise element
                # phase = np.angle(val)
                # phase = np.unwrap(phase)
                # x = np.arange(len(phase))
                # m, q = np.polyfit(x, phase, 1)
                # linear_phase = m * x + q
                # phase -= linear_phase

                # marker_x , marker_y = find_peaks(freq, magn, verbose)
                # marker_y = 10 * np.log10(20 * (np.abs(marker_y)) ** 2)

                # if freq[-1]-freq[0]<1e7:
                #     marker_x = [marker_x[np.argmin(marker_y)]]    
                #     marker_y = [marker_y[np.argmin(marker_y)]]
                
                #                 #markers
                # fig.add_trace(go.Scattergl(
                #     x=marker_x,
                #     y=marker_y,
                #     mode='markers',
                #     name="<b><span style='font-size: 16px'> Initial guess markers (aka minimal points) </span></b><br>",
                #     marker=dict(
                #         color='red',
                #         size=12,
                #         symbol='diamond',
                #         line=dict(width=2, color='White')
                #     )
                # ),row=2*count+2,col=1)
                
                # count+=1
                magn = np.abs(val)
                magn_dB = 10 * np.log10(20 * (np.abs(val)) ** 2)
        
                #angle fixing (unwraps(no jumps over pi)), also deletes linear rise element
                phase = np.angle(val)
                phase = np.unwrap(phase)
                x = np.arange(len(phase))
                m, q = np.polyfit(x, phase, 1)
                linear_phase = m * x + q
                phase -= linear_phase

                marker_x , marker_y = find_peaks(freq, magn, verbose = verbose, window_size= 30,base_freq=2e5)
                marker_y = 10 * np.log10(20 * (np.abs(marker_y)) ** 2)


                if freq[-1]-freq[0]<1e7:
                    marker_x = [marker_x[np.argmin(marker_y)]]    
                    marker_y = [marker_y[np.argmin(marker_y)]]

                #main graph
                fig.add_trace(go.Scattergl(
                    x=freq,
                    y= magn_dB,
                    legendgroup='magnitude',
                    mode='lines',
                    name="<b><span style='font-size: 16px'> Data </span></b><br>",
                    line=dict(color='blue', width=1),
                    opacity=0.7
                ),row=row_count,col=1)

                #markers
                fig.add_trace(go.Scattergl(
                    x=marker_x,
                    y=marker_y,
                    mode='markers',
                    name="<b><span style='font-size: 16px'> Initial guess markers (aka minimal points) </span></b><br>",
                    marker=dict(
                        color='red',
                        size=12,
                        symbol='diamond',
                        line=dict(width=2, color='White')
                    )
                ),row=row_count,col=1)

                point_indexes = np.where(np.isin(freq,marker_x))[0]

                #can be calculated on each point later
                if(freq[-1]-freq[0]>1e7):
                    width = 50
                    do_not_wide=0
                else:
                    do_not_wide=1

                num_traces = len(point_indexes)

                for count,point in enumerate(point_indexes, start=1):
                    if(do_not_wide):
                        freq_tmp = freq
                        phase_temp = phase
                    else:
                        freq_tmp = freq[point-width:point+width]
                        phase_temp = phase[point-width:point+width]

                    if(do_not_wide):
                        re = np.abs(val) * np.cos(phase)
                        im = np.abs(val) * np.sin(phase)
                    else:
                        re = np.abs(val[point-width:point+width]) * np.cos(phase_temp)
                        im = np.abs(val[point-width:point+width]) * np.sin(phase_temp)
                    
                    f0, Qi, Qe, Qr, zfit, popt, pcov, resid, pinit = do_fit_linear(freq_tmp,re,im,f0=freq_tmp[int(len(freq_tmp)/2)])
                    
                    zfit = 20 * np.log10((np.abs(zfit)) ** 2)
                    
                    hue = (count - 1) * (180 / max(1, num_traces - 1)) 
                    # Convert HSL to RGB (Saturation 0.8, Lightness 0.5 for vibrant colors)
                    rgb = colorsys.hls_to_rgb(hue / 360, 0.5, 0.8)
                    
                    legend_label = (
                        f"<b><span style='font-size: 16px'>Fit {count}</span></b><br>"
                        f"f0:  {f0}<br>"
                        f"Q_r: {Qr}<br>"
                        f"Q_e: {Qe}<br>"
                        f"Q_i: {Qi}<br>"
                    )
                    if(verbose):
                        print(f"{count} pcov:{pcov}")
                    
                    #fit
                    #mag
                    fig.add_trace(go.Scattergl(
                        x=freq_tmp,
                        y=zfit,
                        mode='lines',
                        name=legend_label,
                        legendgroup=f'{count}',
                        line=dict(color=f'rgb({int(rgb[0]*255)}, {int(rgb[1]*255)}, {int(rgb[2]*255)})', width=1.5),
                        opacity=1
                    ),row=row_count,col=1)
                    
                    fig.add_trace(go.Scattergl(
                        x=[f0],
                        y=[zfit[np.abs(freq_tmp-f0).argmin()]],
                        mode='markers',
                        name=legend_label,
                        legendgroup=f'{count}',
                        showlegend=False,
                        line=dict(color=f'rgb({int(rgb[0]*255)}, {int(rgb[1]*255)}, {int(rgb[2]*255)})', width=1.5),
                        opacity=1
                    ),row=row_count,col=1)

                    if(args.initial):    
                        fig.add_trace(go.Scattergl(
                            x=freq_tmp,
                            y=10 * np.log10(20 * (np.abs(S21_func_linear(freq_tmp,*pinit))) ** 2),
                            mode='lines',
                            name=f'initial guess:{count}',
                            legendgroup=f'{count}_initial',
                            line=dict(color=f'rgb({int(rgb[0]*128)}, {int(rgb[1]*128)}, {int(rgb[2]*128)})', width=1.5),
                            opacity=1
                        ),row=row_count,col=1)    
                        
                row_count+=1 


    # height_val = 500 * len(filenames)

    height_val = 900

    if height_val <900:
        height_val=900

    fig.update_layout(
        height= height_val,
        title=f"{args.write}",
        template="ggplot2" # Often easier on the eyes for RF data
    )

    if(args.write==None):
        fig.show()   
    else:
        fig.write_html(f"{args.write}.html")