# Import packages

import numpy as np
import matplotlib.pyplot as plt
# import keras
import sys
import os
import logging
import galsim
import cmath as cm
import math
import random
import scipy
from scipy.stats import norm
from astropy.io import fits

from cosmos_params import *

import photutils
from photutils.centroids import centroid_com

sys.path.insert(0,'../scripts/tools_for_VAE/')
from tools_for_VAE import utils
from images_utils import get_scale_radius, get_data, shift_gal, peak_detection, draw_images

rng = galsim.BaseDeviate(None)

########## IMAGES NUMPY ARRAYS GENERATION
# CASE OF PARAMETRIC IMAGES - SIMULATION
def image_generator_sim(cosmos_cat_dir, training_or_test, isolated_or_blended, used_idx=None, nmax_blend=4, max_try=3, mag_cut=28., method_first_shift='noshift',  method_others_shift='uniform', max_dx = 3.2, max_r = 2., do_peak_detection=True, center_brightest = True, max_stamp_size= 64):
    """
    Return numpy arrays: noiseless and noisy image of single galaxy and of blended galaxies as well as the pandaframe including data about the image and the shifts in the test sample generation configuration
    
    Parameters:
    ----------
    cosmos_cat_dir: COSMOS catalog directory
    training_or_test: choice for generating a training or testing dataset
    isolated_or_blended: choice for generation of samples of isolated galaxy images or blended galaxies images
    used_idx: indexes to use in the catalog (to use different parts of the catalog for training/validation/test)
    nmax_blend: maximum number of galaxies in a blended galaxies image
    max_try: maximum number of try before leaving the function (to avoir infinite loop)
    mag_cut: cut in magnitude to select function below this magnitude
    method_first_shift: chosen method for shifting the centered galaxy
    do_peak_detection: boolean to do the peak detection
    """
    # Import the COSMOS catalog
    cosmos_cat = galsim.COSMOSCatalog('real_galaxy_catalog_25.2.fits', dir=cosmos_cat_dir)
    counter = 0
    np.random.seed() # important for multiprocessing !
    
    assert training_or_test in ['training', 'validation', 'test']
    assert isolated_or_blended in ['blended', 'isolated']
    
    while counter < max_try:
        try:
            ud = galsim.UniformDeviate()

            nb_blended_gal = np.random.randint(nmax_blend)+1
            data = {}
            galaxies = []
            mag=[]
            mag_ir=[]
            j = 0
            while j < nb_blended_gal:
                # Chose the part of the catalog used for generation
                if used_idx is not None:
                    idx = np.random.choice(used_idx)
                else:
                    idx = np.random.randint(cosmos_cat.nobject)
                # Generate galaxy
                gal = cosmos_cat.makeGalaxy(idx, gal_type='parametric', chromatic=True, noise_pad_size=0)
                # Compute the magnitude of the galaxy
                _mag_temp = gal.calculateMagnitude(filters['r'].withZeropoint(28.13))
                # Magnitude cut
                if _mag_temp < mag_cut:
                    gal = gal.rotate(ud() * 360. * galsim.degrees)
                    galaxies.append(gal)
                    mag.append(_mag_temp)
                    mag_ir.append(gal.calculateMagnitude(filters['H'].withZeropoint(24.92-22.35*coeff_noise_h)))
                    j += 1


            # Compute ellipticities and magnitude for galaxies in r band before the shifting.
            psf_image = PSF[6].drawImage(nx=max_stamp_size, ny=max_stamp_size, scale=pixel_scale[6])
            images = []
            galaxies_psf = [galsim.Convolve([gal*coeff_exp[6], PSF[6]]) for gal in galaxies]
            for j, gal in enumerate(galaxies_psf):
                temp_img = galsim.ImageF(max_stamp_size, max_stamp_size, scale=pixel_scale[6])

                gal.drawImage(filters['r'], image=temp_img)
                images.append(temp_img)

            for z in range (nb_blended_gal):
                data['redshift_'+str(z)], data['moment_sigma_'+str(z)], data['e1_'+str(z)], data['e2_'+str(z)], data['mag_'+str(z)] = get_data(galaxies[z], images[z], psf_image)
            if nb_blended_gal < nmax_blend:
                for z in range (nb_blended_gal,nmax_blend):
                    data['redshift_'+str(z)], data['moment_sigma_'+str(z)], data['e1_'+str(z)], data['e2_'+str(z)], data['mag_'+str(z)] = 10., 10., 10., 10., 10.


            # Optionally, find the brightest and put it first in the list
            if center_brightest:
                _idx = np.argmin(mag)
                galaxies.insert(0, galaxies.pop(_idx))
                mag.insert(0,mag.pop(_idx))
                mag_ir.insert(0,mag_ir.pop(_idx))

            # Shifts galaxies
            shift = np.zeros((nmax_blend,2))
            if center_brightest == False:
                # Shift the lowest magnitude galaxy
                galaxies[0], shift[0] = shift_gal(galaxies[0], method=method_first_shift, max_dx=max_dx, max_r = max_r)
            # Shift all the other galaxies
            for j,gal in enumerate(galaxies[1:]): 
                galaxies[j+1], shift[j+1] = shift_gal(gal, method=method_others_shift, max_dx=max_dx, max_r = max_r)
            
            # Compute distances of the neighbour galaxies to the lowest magnitude galaxy
            if nb_blended_gal>1:
                distances = [shift[j][0]**2+shift[j][1]**2 for j in range(1,nb_blended_gal)]
                idx_closest_to_peak_galaxy = np.argmin(distances)+1
            else:
                idx_closest_to_peak_galaxy = 0
            
            galaxy_noiseless = np.zeros((10,max_stamp_size,max_stamp_size))
            blend_noisy = np.zeros((10,max_stamp_size,max_stamp_size))

            # Realize peak detection in r-band filter if asked
            if do_peak_detection:
                band = 6
                galaxies_psf = [galsim.Convolve([gal*coeff_exp[band], PSF[band]]) for gal in galaxies]

                images, blend_img = draw_images(galaxies_psf, band, max_stamp_size*2, 'r', sky_level_pixel[band])
                blend_noisy_temp = blend_img.array.data
                peak_detection_output = peak_detection(blend_noisy_temp, band, shift, max_stamp_size*2, 4,nb_blended_gal, training_or_test, dist_cut=0.65/2.)
                if not peak_detection_output:
                    print('No peak detected')
                    raise RuntimeError
                else:
                    idx_closest_to_peak, idx_closest_to_peak_galaxy, center_pix_x, center_pix_y, center_arc_x, center_arc_y, n_peak = peak_detection_output

                # Modify galaxies and shift accordingly
                galaxies = [gal.shift(-center_arc_x, -center_arc_y) for gal in galaxies]
                shift[:nb_blended_gal] -= np.array([center_arc_x, center_arc_y])
            
            # Now draw image in all filters
            for i, filter_name in enumerate(filter_names_all):
                galaxies_psf = [galsim.Convolve([gal*coeff_exp[i], PSF[i]]) for gal in galaxies]
                images, blend_img = draw_images(galaxies_psf, i, max_stamp_size, filter_name, sky_level_pixel[i])
                if isolated_or_blended == 'isolated' or not do_peak_detection:
                    idx_closest_to_peak = 0
                    n_peak = 1

                galaxy_noiseless[i] = images[idx_closest_to_peak].array.data
                blend_noisy[i] = blend_img.array.data

                # # get data for the test sample, data are computed in the 'r' filter
                # if filter_name == 'r':
                #     # need psf to compute ellipticities
                #     print('avant psf.drawImage bande r')
                #     psf_image = PSF[i].drawImage(nx=max_stamp_size, ny=max_stamp_size, scale=pixel_scale[i])
                #     print('apres psf.drawImage bande r')
                #     data['redshift'], data['moment_sigma'], data['e1'], data['e2'], data['mag'] = get_data(galaxies[idx_closest_to_peak], images[idx_closest_to_peak], psf_image)
                #     print('apres getdata bande r')

                #     # Compute data and blendedness
                #     if nb_blended_gal > 1:
                #         data['closest_redshift'], data['closest_moment_sigma'], data['closest_e1'], data['closest_e2'], data['closest_mag'] = get_data(galaxies[idx_closest_to_peak_galaxy], images[idx_closest_to_peak_galaxy], psf_image)
                #         print('apres getdata bande r', i)
                #         img_central = images[idx_closest_to_peak].array
                #         img_others = np.zeros_like(img_central)
                #         for _h, image in enumerate(images):
                #             if _h!=idx_closest_to_peak:
                #                 img_others += image.array
                #         #img_others = np.array([image.array.data for _h, image in enumerate(images) if _h!=idx_closest_to_peak]).sum(axis = 0)
                #         img_closest_neighbour =images[idx_closest_to_peak_galaxy].array# np.array(images[idx_closest_to_peak_galaxy].array.data)
                #         data['blendedness_total_lsst'] = utils.compute_blendedness_total(img_central, img_others)
                #         data['blendedness_closest_lsst'] = utils.compute_blendedness_single(img_central, img_closest_neighbour)
                #         data['blendedness_aperture_lsst'] = utils.compute_blendedness_aperture(img_central, img_others, data['moment_sigma'])
                #     else:
                #         data['closest_redshift'] = np.nan
                #         data['closest_moment_sigma'] = np.nan
                #         data['closest_e1'] = np.nan
                #         data['closest_e2'] = np.nan
                #         data['closest_mag'] = np.nan
                #         data['blendedness_total_lsst'] = np.nan
                #         data['blendedness_closest_lsst'] = np.nan
                #         data['blendedness_aperture_lsst'] = np.nan
            break

        except RuntimeError as e:
            print(e)


    # For testing, return unormalized images and data
    data['nb_blended_gal'] = nb_blended_gal
    data['mag'] = mag[0]
    data['mag_ir'] = mag_ir[0]
    if nb_blended_gal>1:
        data['closest_mag'] = mag[idx_closest_to_peak_galaxy]
        data['closest_mag_ir'] = mag_ir[idx_closest_to_peak_galaxy]
        data['closest_x'] = shift[idx_closest_to_peak_galaxy][0]
        data['closest_y'] = shift[idx_closest_to_peak_galaxy][1]
    else:
        data['closest_mag'] = np.nan
        data['closest_mag_ir'] = np.nan
        data['closest_x'] = np.nan
        data['closest_y'] = np.nan
    data['idx_closest_to_peak'] = idx_closest_to_peak
    data['n_peak_detected'] = n_peak
    data['SNR'] = utils.SNR(galaxy_noiseless, sky_level_pixel, band=6)[1]
    data['SNR_peak'] = utils.SNR_peak(galaxy_noiseless, sky_level_pixel, band=6)[1]
    return galaxy_noiseless, blend_noisy, data, shift





# CASE OF REAL IMAGES
def image_generator_real(cosmos_cat_dir, training_or_test, isolated_or_blended, used_idx=None, nmax_blend=4, max_try=3, mag_cut=28., method_first_shift='noshift', method_others_shift='uniform', max_dx = 3.2, max_r = 2., do_peak_detection=True, center_brightest = True, max_stamp_size= 64):
    """
    Return numpy arrays: noiseless and noisy image of single galaxy and of blended galaxies as well as the pandaframe including data about the image and the shifts in the test sample generation configuration
    
    Parameters:
    ----------
    cosmos_cat_dir: COSMOS catalog directory
    training_or_test: choice for generating a training or testing dataset
    isolated_or_blended: choice for generation of samples of isolated galaxy images or blended galaxies images
    used_idx: indexes to use in the catalog (to use different parts of the catalog for training/validation/test)
    nmax_blend: maximum number of galaxies in a blended galaxies image
    max_try: maximum number of try before leaving the function (to avoir infinite loop)
    mag_cut: cut in magnitude to select function below this magnitude
    method_first_shift: chosen method for shifting the centered galaxy
    do_peak_detection: boolean to do the peak detection
    """
    # Import the COSMOS catalog
    cosmos_cat = galsim.COSMOSCatalog('real_galaxy_catalog_25.2.fits', dir=cosmos_cat_dir)
    counter = 0
    np.random.seed() # important for multiprocessing !
    
    assert training_or_test in ['training', 'validation', 'test']
    assert isolated_or_blended in ['blended', 'isolated']
    
    while counter < max_try:
        try:
            ud = galsim.UniformDeviate()
            real_gal_list = []

            nb_blended_gal = np.random.randint(nmax_blend)+1
            data = {}
            galaxies = []
            mag=[]
            mag_ir=[]
            j = 0
            while j < nb_blended_gal:
                # Chose the part of the catalog used for generation
                if used_idx is not None:
                    idx = np.random.choice(used_idx)
                else:
                    idx = np.random.randint(cosmos_cat.nobject)
                # Generate galaxy
                gal = cosmos_cat.makeGalaxy(idx, gal_type='parametric', chromatic=True, noise_pad_size=0)
                # Compute the magnitude of the galaxy
                _mag_temp = gal.calculateMagnitude(filters['r'].withZeropoint(28.13))
                # Magnitude cut
                if _mag_temp < mag_cut:
                    gal = gal.rotate(ud() * 360. * galsim.degrees)
                    galaxies.append(gal)
                    mag.append(_mag_temp)
                    mag_ir.append(gal.calculateMagnitude(filters['H'].withZeropoint(24.92-22.35*coeff_noise_h)))
                    j += 1
                    
                # Take the real galaxy image only if parametric galaxy is actually created
                if  len(galaxies) == (len(real_gal_list)+1):
                    bp_file = os.path.join(galsim.meta_data.share_dir, 'wfc_F814W.dat.gz')
                    bandpass = galsim.Bandpass(bp_file, wave_type='ang').thin().withZeropoint(25.94)
                    real_gal = cosmos_cat.makeGalaxy(idx, gal_type='real',
                                                    noise_pad_size=max_stamp_size*pixel_scale_lsst)
                    real_gal_list.append(real_gal)

            # Optionally, find the brightest and put it first in the list
            if center_brightest:
                _idx = np.argmin(mag)
                galaxies.insert(0, galaxies.pop(_idx))
                real_gal_list.insert(0, real_gal_list.pop(_idx))
                mag.insert(0,mag.pop(_idx))
                mag_ir.insert(0,mag_ir.pop(_idx))

            # Shifts galaxies
            shift = np.zeros((nmax_blend,2))
            if center_brightest == False:
                # Shift the lowest magnitude galaxy
                galaxies[0], shift[0] = shift_gal(galaxies[0], method=method_first_shift, max_dx=max_dx, max_r = max_r)
            # Shift all the other galaxies
            for j,gal in enumerate(galaxies[1:]):
                galaxies[j+1], shift[j+1] = shift_gal(gal, method=method_others_shift, max_dx=max_dx, max_r = max_r)
            
            # Compute distances of the neighbour galaxies to the lowest magnitude galaxy
            if nb_blended_gal>1:
                distances = [shift[j][0]**2+shift[j][1]**2 for j in range(1,nb_blended_gal)]
                idx_closest_to_peak_galaxy = np.argmin(distances)+1
            else:
                idx_closest_to_peak_galaxy = 0
            
            galaxy_noiseless = np.zeros((10,max_stamp_size,max_stamp_size))
            blend_noisy = np.zeros((10,max_stamp_size,max_stamp_size))
            galaxy_noiseless_real = np.zeros((10,max_stamp_size,max_stamp_size))
            blend_noisy_real = np.zeros((10,max_stamp_size,max_stamp_size))

            # Realize peak detection in r-band filter if asked
            if do_peak_detection:
                band = 6
                galaxies_psf = [galsim.Convolve([gal*coeff_exp[band], PSF[band]]) for gal in galaxies]

                images, blend_img = draw_images(galaxies_psf, band, max_stamp_size*2, 'r', sky_level_pixel[band])
                blend_noisy_temp = blend_img.array.data
                peak_detection_output = peak_detection(blend_noisy_temp, band, shift, max_stamp_size*2, 4,nb_blended_gal, training_or_test, dist_cut=0.65/2.)
                if not peak_detection_output:
                    print('No peak detected')
                    raise RuntimeError
                else:
                    idx_closest_to_peak, idx_closest_to_peak_galaxy, center_pix_x, center_pix_y, center_arc_x, center_arc_y, n_peak = peak_detection_output

                # Modify galaxies and shift accordingly
                galaxies = [gal.shift(-center_arc_x, -center_arc_y) for gal in galaxies]
                shift[:nb_blended_gal] -= np.array([center_arc_x, center_arc_y])

            # shift galaxies for centered configuration 'noshift'
            for k,gal in enumerate(real_gal_list):
                real_gal_list[k], shift[k] = shift_gal(gal, shift_x0=shift[k,0], shift_y0=shift[k,1], method='noshift')
         
            # Draw real images
            galaxies_real_psf = [galsim.Convolve([real_gal*coeff_exp[6], PSF_lsst]) for real_gal in real_gal_list]
            images_real, _ = draw_images(galaxies_real_psf, 6, max_stamp_size, 'r', sky_level_pixel[6], real_or_param = 'real')
            
       
            # Now draw image in all bands
            for i, filter_name in enumerate(filter_names_all):
                galaxies_psf = [galsim.Convolve([gal*coeff_exp[i], PSF[i]]) for gal in galaxies]
                images, blend_img = draw_images(galaxies_psf, i, max_stamp_size, filter_name, sky_level_pixel[i])
                if isolated_or_blended == 'isolated' or not do_peak_detection:
                    idx_closest_to_peak = 0
                    n_peak = 1
                galaxy_noiseless[i] = images[idx_closest_to_peak].array.data
                blend_noisy[i] = blend_img.array.data

                # Rescale real images by flux
                images_real_array = np.zeros((len(images_real), max_stamp_size, max_stamp_size))
                for jj, image_real in enumerate(images_real):
                    img_temp = images[jj]
                    image_real -= np.min(image_real.array)
                    images_real_array[jj] = image_real.array  * np.sum(img_temp.array)/np.sum(image_real.array)

                # real galaxies
                galaxy_noiseless_real[i] = images_real_array[idx_closest_to_peak].data
                for image_real_array in images_real_array:
                    blend_noisy_real[i] += image_real_array\

                # Add noise
                blend_noisy_real_temp = galsim.Image(blend_noisy_real[i], dtype=np.float64)
                poissonian_noise = galsim.PoissonNoise(rng, sky_level=sky_level_pixel[i])
                blend_noisy_real_temp.addNoise(poissonian_noise)
                blend_noisy_real[i] = blend_noisy_real_temp.array.data

                # get data for the test sample
                if filter_name == 'r':
                    # need psf to compute ellipticities
                    psf_image = PSF[i].drawImage(nx=max_stamp_size, ny=max_stamp_size, scale=pixel_scale[i])
                    data['redshift'], data['moment_sigma'], data['e1'], data['e2'], data['mag'] = get_data(galaxies[idx_closest_to_peak], images[idx_closest_to_peak], psf_image, param_or_real = 'param')#real_gal_list[idx_closest_to_peak_galaxy], images_real

                    # Compute data and blendedness
                    if nb_blended_gal > 1:
                        data['closest_redshift'], data['closest_moment_sigma'], data['closest_e1'], data['closest_e2'], data['closest_mag'] = get_data(galaxies[idx_closest_to_peak_galaxy], images[idx_closest_to_peak_galaxy], psf_image, param_or_real = 'param')#real_gal_list[idx_closest_to_peak_galaxy]
                        img_central = images[idx_closest_to_peak].array
                        img_others = np.zeros_like(img_central)
                        for _h, image in enumerate(images):
                            if _h!=idx_closest_to_peak:
                                img_others += image.array

                        img_closest_neighbour =images[idx_closest_to_peak_galaxy].array
                        data['blendedness_total_lsst'] = utils.compute_blendedness_total(img_central, img_others)
                        data['blendedness_closest_lsst'] = utils.compute_blendedness_single(img_central, img_closest_neighbour)
                        data['blendedness_aperture_lsst'] = utils.compute_blendedness_aperture(img_central, img_others, data['moment_sigma'])
                    else:
                        data['closest_redshift'] = np.nan
                        data['closest_moment_sigma'] = np.nan
                        data['closest_e1'] = np.nan
                        data['closest_e2'] = np.nan
                        data['closest_mag'] = np.nan
                        data['blendedness_total_lsst'] = np.nan
                        data['blendedness_closest_lsst'] = np.nan
                        data['blendedness_aperture_lsst'] = np.nan
            break

        except RuntimeError as e:
            print(e)

    data['nb_blended_gal'] = nb_blended_gal
    data['mag'] = mag[0]
    data['mag_ir'] = mag_ir[0]
    if nb_blended_gal>1:
        data['closest_mag'] = mag[idx_closest_to_peak_galaxy]
        data['closest_mag_ir'] = mag_ir[idx_closest_to_peak_galaxy]
        data['closest_x'] = shift[idx_closest_to_peak_galaxy][0]
        data['closest_y'] = shift[idx_closest_to_peak_galaxy][1]
    else:
        data['closest_mag'] = np.nan
        data['closest_mag_ir'] = np.nan
        data['closest_x'] = np.nan
        data['closest_y'] = np.nan
    data['idx_closest_to_peak'] = idx_closest_to_peak
    data['n_peak_detected'] = n_peak
    data['SNR'] = utils.SNR(galaxy_noiseless, sky_level_pixel, band=6)[1]
    data['SNR_peak'] = utils.SNR_peak(galaxy_noiseless, sky_level_pixel, band=6)[1]
    return galaxy_noiseless_real, blend_noisy_real, data, shift
