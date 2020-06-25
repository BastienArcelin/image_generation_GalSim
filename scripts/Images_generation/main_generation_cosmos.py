# Import packages

import numpy as np
import matplotlib.pyplot as plt
import sys
import os
import logging
import galsim
import cmath as cm
import matplotlib.pyplot as plt
from multiprocess import *
import pandas as pd
from tqdm import tqdm, trange

sys.path.insert(0,'../scripts/tools_for_VAE/')
import tools_for_VAE
from tools_for_VAE import utils

from images_generator import image_generator_sim, image_generator_real

# The script is used as, eg,
# >> python main_blended_generation_cosmos.py centered/ training isolated noshift false 10 1000 1
# to produce 10 files in the training sample with 1000 images each of isolated galaxy centered on the image with no shift.
case = str(sys.argv[1]) # centered/ miscentered_0.1/ miscentered_peak/ 
gal_type = str(sys.argv[2]) #simulation or real/
training_or_test = str(sys.argv[3]) # training test validation
isolated_or_blended = str(sys.argv[4]) #isolated blended
method_shift = str(sys.argv[5]) # noshift uniform uniform+betaprime
do_peak_detection = str(sys.argv[6]).lower() == 'true'
N_files = int(sys.argv[7]) # Nb of files to generate
N_per_file = str(sys.argv[8]) # Number of galaxies per file
nmax_blend = int(sys.argv[9]) # Maximum number of galaxies on an image
assert training_or_test in ['training', 'validation', 'test']

# Fixed parameters:
max_try = 100 # maximum number of try before leaving the function (to avoir infinite loop)
mag_cut = 27.5 # cut in magnitude to select galaxies below this magnitude
center_brightest = True # Center the brightest galaxy (i.e. the galaxy with the highest magnitude)

# Method to shift centered galaxy
if isolated_or_blended == 'isolated':
    # where to save images and data
    save_dir = '/sps/lsst/users/barcelin/data/isolated_galaxies/' + case + training_or_test
    # what to call those files
    root = 'galaxies_isolated_20191024_'
    # Maximum number of galaxies on the image. Here, "isolated" so only 1 galaxy.
    nmax_blend = 1
elif isolated_or_blended == 'blended':
    # where to save images and data
    save_dir = '/sps/lsst/users/barcelin/data/blended_galaxies/' + case + training_or_test
    # what to call those files
    root = 'galaxies_blended_20191024_'
    # Maximum number of galaxies on the image. Here, "isolated" so only 1 galaxy.
    nmax_blend = nmax_blend
else:
    raise NotImplementedError
# Loading the COSMOS catalog
cosmos_cat = galsim.COSMOSCatalog('real_galaxy_catalog_25.2.fits', dir='/sps/lsst/users/barcelin/COSMOS_25.2_training_sample') #dir=os.path.join(galsim.meta_data.share_dir,'COSMOS_25.2_training_sample'))#
# Path to the catalog
cosmos_cat_dir = '/sps/lsst/users/barcelin/COSMOS_25.2_training_sample'
# Select galaxies to keep for the test sample
if training_or_test == 'test':
    used_idx = np.arange(5000)
# Rest of the galaxies used for training and validation
else:
    used_idx = np.arange(5000,cosmos_cat.nobjects)

# keys for data objects
keys = ['nb_blended_gal', 'SNR', 'SNR_peak', 'redshift', 'moment_sigma', 'e1', 'e2', 'mag', 'mag_ir', 'closest_x', 'closest_y', 'closest_redshift', 'closest_moment_sigma', 'closest_e1', 'closest_e2', 'closest_mag', 'closest_mag_ir', 'blendedness_total_lsst', 'blendedness_closest_lsst', 'blendedness_aperture_lsst', 'idx_closest_to_peak', 'n_peak_detected']

for icat in trange(N_files):
    # Run params
    root_i = root+str(icat)

    galaxies = []
    shifts = []
    if training_or_test == 'test':
        # If test, create Pandas DataFrame to return properties of test galaxies
        df = pd.DataFrame(index=np.arange(N_per_file), columns=keys)
    
    # Depending of type of galaxies you wand (simulation or real galaxies) use the correct generating function
    if gal_type == 'simulation':
        res = utils.apply_ntimes(image_generator_sim, N_per_file, (cosmos_cat_dir, training_or_test, isolated_or_blended, save_dir, used_idx, nmax_blend, max_try, mag_cut, method_shift, do_peak_detection, center_brightest))
    elif gal_type == 'real':
        res = utils.apply_ntimes(image_generator_real, N_per_file, (cosmos_cat_dir, training_or_test, isolated_or_blended, save_dir, used_idx, nmax_blend, max_try, mag_cut, method_shift, do_peak_detection, center_brightest))

    
    for i in trange(N_per_file):
        # Save data and shifts for all training, validation and test files
        gal_noiseless, blend_noisy, data, shift = res[i]
        assert set(data.keys()) == set(keys)
        df.loc[i] = [data[k] for k in keys]
        shifts.append(shift)
        galaxies.append((gal_noiseless, blend_noisy))

    # Save noisy blended images and denoised single central galaxy images
    np.save(os.path.join(save_dir, root_i+'_images.npy'), galaxies)
    # Save data and shifts
    df.to_csv(os.path.join(save_dir, root_i+'_data.csv'), index=False)
    np.save(os.path.join(save_dir, root_i+'_shifts.npy'), np.array(shifts))
    
    del galaxies, res, shifts, df