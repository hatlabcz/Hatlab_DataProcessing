from typing import Tuple, Any, Optional, Union, Dict, List

import numpy as np
import matplotlib.pyplot as plt
import lmfit
from lmfit.model import ModelResult
import h5py
from Hatlab_DataProcessing.fitter.fitter_base import Fit, FitResult
from Hatlab_DataProcessing.helpers.unit_converter import freqUnit, rounder, realImag2magPhase

TWOPI = 2 * np.pi
PI = np.pi


def getVNAData(filename, freq_unit='Hz', plot=1, trim=0):
    trim_end = None if trim == 0 else -trim
    f = h5py.File(filename, 'r')
    freq = f['Freq'][()][trim: trim_end] * freqUnit(freq_unit)
    phase = f['S21'][()][1][trim: trim_end] / 180 * np.pi
    mag = f['S21'][()][0][trim: trim_end]
    f.close()

    lin = 10 ** (mag / 20.0)
    real = lin * np.cos(phase)
    imag = lin * np.sin(phase)

    if plot:
        plt.figure('mag')
        plt.plot(freq / 2 / np.pi, mag)
        plt.figure('phase')
        plt.plot(freq / 2 / np.pi, phase)

    return (freq, real, imag, mag, phase)


def cav_ref_func(freq, Qext, Qint, f0):
    """"reflection function of a harmonic oscillator"""
    omega0 = f0 * TWOPI
    delta = freq * TWOPI - omega0
    S_11_nume = 1 - Qint / Qext + 1j * 2 * Qint * delta / omega0
    S_11_denom = 1 + Qint / Qext + 1j * 2 * Qint * delta / omega0
    S11 = (S_11_nume / S_11_denom)
    return S11


class CavReflectionResult():
    def __init__(self, lmfit_result: lmfit.model.ModelResult):
        self.lmfit_result = lmfit_result
        self.params = lmfit_result.params
        self.f0 = self.params["f0"].value
        self.Qext = self.params["Qext"].value
        self.Qint = self.params["Qint"].value
        self.Qtot = self.Qext * self.Qint / (self.Qext + self.Qint)
        self.freqData = lmfit_result.userkws[lmfit_result.model.independent_vars[0]]

    def plot(self, **figArgs):
        real_fit = self.lmfit_result.best_fit.real
        imag_fit = self.lmfit_result.best_fit.imag
        mag_fit, phase_fit = realImag2magPhase(real_fit, imag_fit)
        mag_data, phase_data = realImag2magPhase(self.lmfit_result.data.real,
                                                 self.lmfit_result.data.imag)

        fig_args_ = dict(figsize=(12, 5))
        fig_args_.update(figArgs)
        plt.figure(**fig_args_)
        plt.subplot(1, 2, 1)
        plt.title('mag (dB pwr)')
        plt.plot(self.freqData, mag_data, '.')
        plt.plot(self.freqData, mag_fit)
        plt.subplot(1, 2, 2)
        plt.title('phase')
        plt.plot(self.freqData, phase_data, '.')
        plt.plot(self.freqData, phase_fit)
        plt.show()

    def print(self):
        print(f'f (Hz): {rounder(self.f0, 9)}+-{rounder(self.params["f0"].stderr, 9)}')
        print(f'Qext: {rounder(self.Qext, 5)}+-{rounder(self.params["Qext"].stderr, 5)}')
        print(f'Qint: {rounder(self.Qint, 5)}+-{rounder(self.params["Qint"].stderr, 5)}')
        print('Q_tot: ', rounder(self.Qtot, 5))
        print('T1 (s):', rounder(self.Qtot / self.f0 / 2 / np.pi, 5), '\nMaxT1 (s):',
              rounder(self.Qint / self.f0 / 2 / np.pi, 5))
        print('kappa/2Pi: ', rounder(self.f0 / self.Qtot / 1e6), 'MHz')


class CavReflection(Fit):
    @staticmethod
    def model(coordinates, Qext, Qint, f0, magBack, phaseOff) -> np.ndarray:
        """"reflection function of a harmonic oscillator"""
        S11 = magBack * cav_ref_func(coordinates, Qext, Qint, f0) * np.exp(1j * phaseOff)
        return S11

    @staticmethod
    def guess(coordinates, data):
        freq = coordinates
        phase = np.unwrap(np.angle(data))
        mag = np.abs(data)

        f0Guess = freq[np.argmin(mag)]  # smart guess of "it's probably the lowest point"
        magBackGuess = np.average(mag[:int(len(freq) / 5)])
        phaseOffGuess = phase[np.argmin(mag)]

        # guess algorithm from https://lmfit.github.io/lmfit-py/examples/example_complex_resonator_model.html
        Q_min = 0.1 * (f0Guess / (freq[-1] - freq[0]))  # assume the user isn't trying to fit just a small part of a resonance curve
        delta_f = np.diff(freq)  # assume f is sorted
        min_delta_f = delta_f[delta_f > 0].min()
        Q_max = f0Guess / min_delta_f  # assume data actually samples the resonance reasonably
        QtotGuess = np.sqrt(Q_min * Q_max)  # geometric mean, why not?
        QextGuess = QtotGuess / (1 - np.abs(data[np.argmin(mag)]))
        QintGuess = 1 / (1 / QtotGuess + 1 / QextGuess)

        Qext = lmfit.Parameter("Qext", value=QextGuess, min=QextGuess / 100, max=QextGuess * 100)
        Qint = lmfit.Parameter("Qint", value=QintGuess, min=QintGuess / 100, max=QintGuess * 100)
        f0 = lmfit.Parameter("f0", value=f0Guess, min=freq[0], max=freq[-1])
        magBack = lmfit.Parameter("magBack", value=magBackGuess, min=magBackGuess / 1.1, max=magBackGuess * 1.1)
        phaseOff = lmfit.Parameter("phaseOff", value=phaseOffGuess, min=-PI, max=PI)

        return dict(Qext=Qext, Qint=Qint, f0=f0, magBack=magBack, phaseOff=phaseOff)

    def run(self, *args: Any, **kwargs: Any) -> CavReflectionResult:
        lmfit_result = self.analyze(self.coordinates, self.data, *args, **kwargs)
        return CavReflectionResult(lmfit_result)



class CavReflectionResult_Phase():
    def __init__(self, lmfit_result: lmfit.model.ModelResult):
        self.lmfit_result = lmfit_result
        self.params = lmfit_result.params
        self.f0 = self.params["f0"].value
        self.Qext = self.params["Qext"].value
        self.Qint = self.params["Qint"].value
        self.Qtot = self.Qext * self.Qint / (self.Qext + self.Qint)
        self.freqData = lmfit_result.userkws[lmfit_result.model.independent_vars[0]]

    def plot(self, **figArgs):
        phase_fit = self.lmfit_result.best_fit
        phase_data = self.lmfit_result.data

        fig_args_ = dict(figsize=(7, 5))
        fig_args_.update(figArgs)
        plt.figure(**fig_args_)
        plt.title('phase')
        plt.plot(self.freqData, phase_data, '.')
        plt.plot(self.freqData, phase_fit)
        plt.show()

    def print(self):
        print(f'f (Hz): {rounder(self.f0, 9)}+-{rounder(self.params["f0"].stderr, 9)}')
        print(f'Qext: {rounder(self.Qext, 5)}+-{rounder(self.params["Qext"].stderr, 5)}')
        print(f'Qint: {rounder(self.Qint, 5)}+-{rounder(self.params["Qint"].stderr, 5)}')
        print('Q_tot: ', rounder(self.Qtot, 5))
        print('T1 (s):', rounder(self.Qtot / self.f0 / 2 / np.pi, 5), '\nMaxT1 (s):',
              rounder(self.Qint / self.f0 / 2 / np.pi, 5))
        print('kappa/2Pi: ', rounder(self.f0 / self.Qtot / 1e6), 'MHz')


class CavReflectionPhaseOnly(Fit):
    def pre_process(self):
        self.data = np.unwrap(np.angle(self.data))

    @staticmethod
    def model(coordinates, Qext, Qint, f0, phaseOff, eDelay) -> np.ndarray:
        """"reflection function of a harmonic oscillator"""
        S11 = cav_ref_func(coordinates, Qext, Qint, f0)
        S11 *= np.exp(1j * (phaseOff+eDelay * (coordinates - f0) * TWOPI))
        phase = np.unwrap(np.angle(S11))
        return phase

    @staticmethod
    def guess(coordinates, data):
        freq = coordinates
        phase = data

        f0_idx = int(np.floor(np.average(np.where(abs(phase - np.average(phase)) < 0.2))))
        f0Guess = freq[f0_idx]
        phaseOffGuess = np.mean(phase)
        if phase[-1] > phase[0]:
            eDelayGuess = (phase[-1] - phase[0]- PI) / (freq[-1] - freq[0]) / TWOPI
        else:
            if phase[-1] > phase[0]:
                eDelayGuess = (phase[-1] - phase[0] + PI) / (freq[-1] - freq[0]) / TWOPI

        # guess algorithm from https://lmfit.github.io/lmfit-py/examples/example_complex_resonator_model.html
        Q_min = 0.1 * (f0Guess / (freq[-1] - freq[0]))  # assume the user isn't trying to fit just a small part of a resonance curve
        delta_f = np.diff(freq)  # assume f is sorted
        min_delta_f = delta_f[delta_f > 0].min()
        Q_max = f0Guess / min_delta_f  # assume data actually samples the resonance reasonably
        QtotGuess = np.sqrt(Q_min * Q_max)  # geometric mean, why not?
        QextGuess = QtotGuess / (1 - np.abs(data[f0_idx]))
        QintGuess = 1 / (1 / QtotGuess + 1 / QextGuess)

        Qext = lmfit.Parameter("Qext", value=QextGuess, min=QextGuess / 100, max=QextGuess * 100)
        Qint = lmfit.Parameter("Qint", value=QintGuess, min=QintGuess / 100, max=QintGuess * 100)
        f0 = lmfit.Parameter("f0", value=f0Guess, min=freq[0], max=freq[-1])
        phaseOff = lmfit.Parameter("phaseOff", value=phaseOffGuess, min=-TWOPI, max=TWOPI)
        eDelay = lmfit.Parameter("eDelay", value=eDelayGuess)

        return dict(Qext=Qext, Qint=Qint, f0=f0, phaseOff=phaseOff, eDelay=eDelay)

    def run(self, *args: Any, **kwargs: Any) -> CavReflectionResult_Phase:
        lmfit_result = self.analyze(self.coordinates, self.data, *args, **kwargs)
        return CavReflectionResult_Phase(lmfit_result)




if __name__ == '__main__':
    filepath = r'L:\Data\WISPE3D\Modes\20210809\CavModes\Cav'
    (freq, real, imag, mag, phase) = getVNAData(filepath, plot=0)

    cavRef = CavReflectionPhaseOnly(freq, real + 1j * imag)
    results = cavRef.run(params={"Qext": lmfit.Parameter("Qext", value=3.48354e+03), "Qint": lmfit.Parameter("Qint", value=7e3)})
    results.plot()
    results.print()

    # results = cavRef.run(dry=True, params={"Qext": lmfit.Parameter("Qext", value=3.48354e+03), "Qint": lmfit.Parameter("Qint", value=7e3)})
    # results.lmfit_result.plot()