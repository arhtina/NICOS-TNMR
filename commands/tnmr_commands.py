# *****************************************************************************
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc.,
# 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
#
# Module authors:
#   Davis V. Garrad <davis.last@psi.ch>
#
# *****************************************************************************

import time
import math
from datetime import datetime
import traceback

from nicos import session
from nicos.core.data import DataManager
from nicos.core.data.dataset import PointDataset, ScanDataset
import nicos.core.constants as consts
from nicos.commands import helparglist, usercommand, parallel_safe
from nicos.commands.basic import sleep as nicossleep
from nicos.commands.device import maw
from nicos.utils import createThread

TNMR_CURRENTLY_SCANNING = None

@usercommand
class tnmr_scan:
    '''Always acts as a context manager for the data manager. Only the top level tnmr_scan object actually controls the opening and closing of files. '''
    def __init__(self):
        self.toplevel = False

    def __enter__(self):
        global TNMR_CURRENTLY_SCANNING
        
        if(TNMR_CURRENTLY_SCANNING is None):
            dm = DataManager()
            db = dm.beginScan()
            TNMR_CURRENTLY_SCANNING = dm
            self.toplevel = True
            
        return TNMR_CURRENTLY_SCANNING
            
    def __exit__(self, exc_type, exc_value, traceback):
        global TNMR_CURRENTLY_SCANNING
        if not(TNMR_CURRENTLY_SCANNING is None) and (self.toplevel):
            TNMR_CURRENTLY_SCANNING.finishScan()
            TNMR_CURRENTLY_SCANNING = None
            session.log.info('Closing scan file context')
        return False
    
@usercommand
@parallel_safe
@helparglist('pulse width (us), pulse height (a.u.), delay time (us), phase cycle (str,  e.g., "0 1 2 3")')
def generate_pulse(pw, ph, dt, pc):
    """
    Generates the necessary dictionary for adding a pulse to the NMR pulse sequence, to be fed to TNMR via the 'go' command.
    Example:

    p_180 = generate_pulse(5,   40, 1,  '0 0 2 2')
    p_90  = generate_pulse(2.5, 40, 50, '0 0 0 0')
    TNMR_MODULE_NAME.sequence_data = [ p_180, p_90, p_180 ]
    TNMR_MODULE_NAME.compile_and_run()
    """
    d = { 'pulse_width': pw, 'pulse_height': ph, 'delay_time': dt, 'phase_cycle': pc }
    
    return d
    

@usercommand
@parallel_safe
@helparglist('a pulse sequence to be copied and altered, pulse(s) to be scanned (zero-indexed) (in the case of multiple, all will scan concurrently), variable name (i.e., "pulse_width", "pulse_height", "delay_time", or "phase_cycle"), list of values')
def generate_sequences(base_sequence, pulse_indices, var_name, vals):
    try:
        pulse_indices = list(pulse_indices) # convert to list if tuple, single element, etc.. This is so we can just treat it homogeneously throughout the function
    except:
        try:
            pulse_indices = [ pulse_indices ]
        except:
            raise TypeError

    ret = []
    
    for v in vals:
        temp_seq = []
        for i in range(len(base_sequence)): # per-pulse
            temp_seq += [base_sequence[i].copy()]
    
            if(i in pulse_indices):
                temp_seq[i][var_name] = v
        ret += [temp_seq]

    return ret

@usercommand
@parallel_safe
@helparglist('start time (us), end time (us), number of points (end inclusive)')
def log_durations(s, e, N):
    equidist = [(math.log(s) + (math.log(e) - math.log(s))*i/(N-1)) for i in range(0, N) ]
    return [ math.exp(a) for a in equidist ]

@usercommand
@parallel_safe
@helparglist('the TNMR instance/virtual device to pull parameters from, a pulse sequence to estimate')
def estimate_sequence_length_from_device(dev, seq):
    eta = 0.0 # seconds
    tnmr = session.getDevice(dev)
    eta += tnmr.acquisition_time * 1e-6
    eta += tnmr.pre_acquisition_time * 1e-6
    eta += tnmr.post_acquisition_time * 1e-3
    for i in seq:
        eta += i['delay_time'] * 1e-6
        eta += i['pulse_width'] * 1e-6
    eta *= tnmr.num_acqs
    return eta
   
@usercommand
@parallel_safe
@helparglist('a dictionary of parameters (acquisition_time, pre_acquisition_time, post_acquisition_time, and num_acqs), a pulse sequence to estimate') 
def estimate_sequence_length(params, seq):
    eta = 0.0 # seconds
    eta += params['acquisition_time'] * 1e-6
    eta += params['pre_acquisition_time'] * 1e-6
    eta += params['post_acquisition_time'] * 1e-3
    for i in seq:
        eta += i['delay_time'] * 1e-6
        eta += i['pulse_width'] * 1e-6
    eta *= params['num_acqs']
    return eta

@usercommand
@parallel_safe
@helparglist('the TNMR instance/virtual device to be used, a sequence of pulse sequences to estimate')
def estimate_scan_length_from_device(dev, scan_seq):
    total_eta = 0.0
    for j in scan_seq:
        total_eta += estimate_sequence_length_from_device(dev, j)
    return total_eta

@usercommand
@parallel_safe
@helparglist('a dictionary of parameters (acquisition_time, pre_acquisition_time, post_acquisition_time, and num_acqs), a sequence of pulse sequences to estimate')
def estimate_scan_length(params, scan_seq):
    total_eta = 0.0
    for j in scan_seq:
        total_eta += estimate_sequence_length(params, j)
    return total_eta      

@usercommand
@parallel_safe
@helparglist('seconds')
def timestring(seconds):
    days = int(seconds // (24*3600))
    hours = int(seconds // 3600)
    minutes = int(seconds // 60)

    if(seconds > 24*3600):
        etastr = f'{days}d{hours-(24*3600)*days}h'
    elif(seconds > 3600):
        etastr = f'{hours}h{minutes - hours*60}m'
    elif(seconds > 60):
        etastr = f'{minutes}m{int(seconds) - minutes*60}s'
    elif(seconds > 1):
        etastr = f'{seconds:.1f}s'
    elif(seconds > 1e-3):
        etastr = f'{seconds*1e3:.1f}ms'
    elif(seconds > 1e-6):
        etastr = f'{seconds*1e6:.1f}us'
    elif(seconds > 1e-9):
        etastr = f'{seconds*1e9:.1f}ns'
    
    endtime = time.time() + seconds
    enddatetime = datetime.fromtimestamp(endtime)
    etastr += f' ({enddatetime})'
        
    return etastr

@usercommand
@parallel_safe
@helparglist('a pulse sequence to display')
def print_sequence(seq):
    session.log.info('------------------------')
    session.log.info('PW      |PH      |DT      |PC')
    for i in seq:
        delay_time = i['delay_time']
        
        session.log.info(f'{i["pulse_width"]:<8}|{i["pulse_height"]:<8}|{delay_time:<8}|{i["phase_cycle"]}')
    session.log.info('------------------------')

@usercommand
@parallel_safe
def get_tnmr_params(dev):
    tnmr = session.getDevice(dev)
    params_dictionary = {
                          'acquisition_time':      dev.acquisition_time,
                          'ringdown_time':         dev.ringdown_time,
                          'pre_acquisition_time':  dev.pre_acquisition_time,
                          'post_acquisition_time': dev.post_acquisition_time,
                          'acq_phase_cycle':       dev.acq_phase_cycle,
                          'obs_freq':              dev.obs_freq,
                          'num_acqs':              dev.num_acqs,
                          'actual_num_acqs':       dev.num_acqs_actual,
                        }
    return params_dictionary

@usercommand
@helparglist('the reference name of the tnmr module, a pulse sequence to scan')
def scan_sequence(dev, seq, additional_saving_lambdas={}):
    try:
        tnmr = session.getDevice(dev)
        with tnmr_scan() as dm: # open a file if one is not already opened; if one is, this just gives us a reference to the appropriate datamanager.
            pb = dm.beginPoint()
            
            tnmr.sequence_data = seq
            print_sequence(seq)
            estimated_length = estimate_sequence_length_from_device(dev, seq)
            session.log.info(f'Point ETA: {timestring(estimated_length)}')
            tnmr.compile_and_run(False)
            
            finished = False
            starttime = time.time() # To signal when measurement started (approximately. This will not be nanosecond-precise, but it's good enough for our purposes)
            
            while not(finished):
                data = tnmr.read() # get latest data, with records about the # of acquisitions that have been performed.
                
                finished = (tnmr.status()[0] <= 200) # at the start so final values will be written
                nicossleep(tnmr.pollinterval) # A metric as good as any
                if(finished):
                    st = time.time() # Start a timeout clock, essentially
                    while (time.time() - st < 30) and (tnmr.num_acqs_actual != tnmr.num_acqs):
                        nicossleep(0.5) # get up to date values
                        tnmr.read()
                
                # Now we need to put our sequence (list of dictionaries) into the form that our file handler wants (dictionary of dictionaries). The keys on the sequences should be informative of the order, so we just set them as the indices of the original list because that will never be unclear.
                sequence_dictionary = {}
                for i in range(len(seq)):
                    sequence_dictionary[i] = seq[i]
                
                # Construct a whole dictionary for all the different values we want to pass to the file writer. The key is going to be the key of the data in the end; in the NeXus handler, I've programmed in some "magic" identifiers, such as signal:, axes:, auxiliary_signal:, metadata/, and environment/. These each designate a different place for the data to reside ('/') or be given a NeXus attribute (':').and/or jhavereside and 
                params_dict = get_tnmr_params(dev)
                full_value_dict = {
                    'signal:tnmr_reals':               (starttime, data['reals']), 
                    'auxiliary_signals:tnmr_imags':    (starttime, data['imags']),  
                    'axes:tnmr_times':                 (starttime, data['t']),
                    'tnmr_sequence':                   (starttime, sequence_dictionary),
                    'tnmr_params':                     (starttime, params_dict),
                    'metadata/nucleus':                (starttime, tnmr.nucleus),
                    'metadata/sample':                 (starttime, tnmr.sample),
                    'metadata/comments':               (starttime, tnmr.comments),
                }
                for fkey, func in additional_saving_lambdas.items():
                    try:
                        full_value_dict['environment/'+fkey] = (starttime, func())
                    except:
                        session.log.warning(f'Could not acquire parameter `{fkey}` for writing into NeXus file. Traceback: \n{traceback.format_exc()}')
                        pass
            
                dm.putValues(full_value_dict)                        
            dm.finishPoint()
    except Exception as e:
        import traceback
        session.log.warning(traceback.format_exc())

@usercommand
@helparglist('the reference name of the tnmr module, a list of pulse sequences to scan over, a list of (name, lambda) tuples to call (no argument) to be added to the save file')
def scan_sequences(dev, sequence_list, additional_saving_lambdas={}):
    global TNMR_CURRENTLY_SCANNING
    
    st = time.time()
    N = len(sequence_list)
    
    initial_estimate = estimate_scan_length_from_device(dev, sequence_list)
    session.log.info(f'Beginning scan. ETA: {timestring(initial_estimate)}')
    
    with tnmr_scan(): # Make sure that everything is put together in one file!
        for i in range(N):
            seq = sequence_list[i]
            etascan = timestring(estimate_scan_length_from_device(dev, sequence_list[i:]))
            session.log.info(f'Beginning point {i+1}/{N}' + (f' ({float(i)/(N-1)*100:.0f}% complete)' if N>1 else ''))
            session.log.info(f'Scan ETA:  {etascan}')  
            scan_sequence(dev, seq, additional_saving_lambdas)
      
    et = time.time()
    dt = et - st
    
    error = abs(dt - initial_estimate) / initial_estimate * 100.0
    session.log.info(f'Finished scan. Took {timestring(dt)} (error of {error:.0f}% from initial estimate, {error/N:.0f}%/point, {timestring(error/N)} per point).')
    
@usercommand
@helparglist('the device whose parameters shoudl be updated, a dictionary of the parameters')
def update_device_parameters(dev, dic):
    for k,v in dic.items():
        setattr(dev, k, v)
