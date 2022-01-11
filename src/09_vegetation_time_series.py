'''
Similar to the generation of the L1C TOA scenarios, this script generates
a set of vegetation time series scenarios.

For each scenario, the timing and value of the start, peak and end of season
is calculated using the Phenolopy package that is heavily inspired by TIMESAT.

Many thanks @lewistrotter for providing Phenolopy
(see: https://github.com/lewistrotter/Phenolopy) avialable under Apache 2.0 licence.
'''

import glob
import logging
import matplotlib
import pandas as pd
import numpy as np
import xarray as xr

from pathlib import Path
from datetime import datetime
from datetime import date
from typing import Tuple
from typing import List
from typing import Dict
from copy import deepcopy
import geopandas as gpd
import matplotlib.pyplot as plt

from _phenolopy import remove_outliers
from _phenolopy import interpolate
from _phenolopy import smooth
from _phenolopy import calc_phenometrics
from _find_datasets import get_data_and_uncertainty_files
from agrisatpy.io import SatDataHandler
from agrisatpy.io.sentinel2 import Sentinel2Handler

from logger import get_logger

# setup logger -> will write log file to the /../log directory
logger = get_logger('l4_phenology')

plt.style.use('ggplot')
matplotlib.rc('xtick', labelsize=20) 
matplotlib.rc('ytick', labelsize=20)


def _calc_pheno_metrics(xds: xr.Dataset) -> Dict[str, xr.Dataset]:
    """
    Calculation of the phenological metrics using ``Phenolopy``.

    Steps:
        1. Remove outliers using a moving median filter
        2. Interpolate NaNs linearly
        3. Smooth data using Savitzky-Golay
        4. Calculate SOS, POS, EOS using the seasonal amplitude

    :param xds:
        ``xarray`` dataset containing the vegetation parameter/index
        stacked over time
    :return:
        dictionary with two items: 'pheno_metrics' is a ``xarray``
        dataset with pixel-based pheno-metrics. 'ds' contains the smoothed
        per-pixel time series as another ``xarray`` dataset.
    """
    
    # remove outliers using median filter
    ds = remove_outliers(ds=xds, method='median', user_factor=2, z_pval=0.05)

    # interpolate nans linearly
    ds = interpolate(ds=ds, method='interpolate_na')

    # smooth data using Savitzky-Golay filter
    ds = smooth(ds=ds, method='savitsky', window_length=3, polyorder=1)

    # calculate the phenometrics
    pheno_ds = calc_phenometrics(
        da=ds['veg_index'],
        peak_metric='pos',
        base_metric='bse',
        method='seasonal_amplitude',
        factor=0.2,
        thresh_sides='two_sided'
    )

    return {'pheno_metrics': pheno_ds, 'ds': ds}


def read_data_and_uncertainty(
        data_df: pd.DataFrame,
        in_file_aoi: Path,
        vi_name: str,
        out_dir_plots: Path
    ) -> Tuple[pd.DataFrame, List[Sentinel2Handler]]:
    """
    This function reads the selected vegetation index (computed in step 7)
    and the associated standard uncertainty in a uarray (from uncertainties)
    and stores the read data as new columns in data_df.

    :param data_df:
        dataframe returned from ``get_data_and_uncertainty``
    :param in_file_aoi:
        shapefile defining the study area
    :param vi_name:
        name of the vegetation index or parameter to process (e.g., NDVI)
    :param out_dir_plots:
        directory where to store scene quicklooks (might be helpful for
        result interpretation)
    :return:
        input dataframe with read data + list of read vegetation data and
        their absolute uncertainty per image acquisition date
    """

    # loop over datasets (single acquisition dates) and read the data
    # (vegetation index/ parameter + standard uncertainty)
    update_list = []
    ts_stack_dict = {}
    orig_vi_dict = {}
    unc_dict = {}

    for _, record in data_df.iterrows():

        # read S2 banstack plus its SCL file to mask out clouds and shadows
        s2_stack = Sentinel2Handler()
        s2_stack.read_from_bandstack(
            fname_bandstack=Path(record.filename_bandstack),
            in_file_aoi=in_file_aoi,
            band_selection=['B02','B03','B04','B08']
        )

        # mask clouds and cloud shadows (if any) and store the cloudy pixel percentage
        cloud_coverage = s2_stack.get_cloudy_pixel_percentage()

        # plot quicklooks and save them
        plot_dir = out_dir_plots.joinpath(record.date.strftime('%Y%m%d'))
        if not plot_dir.exists():
            plot_dir.mkdir()
        fname_rgb = plot_dir.joinpath('rgb_quicklook.png')
        fname_nir = plot_dir.joinpath('falsecolor-nir_quicklook.png')
        fname_scl = plot_dir.joinpath('scene-classification_quicklook.png')
        fname_vi = plot_dir.joinpath(f'{vi_name.lower()}-nominal_quicklook.png')
        fname_unc = plot_dir.joinpath(f'{vi_name.lower()}-stdunc_quicklook.png')

        # fig_rgb = s2_stack.plot_rgb()
        # fig_rgb.savefig(fname=fname_rgb, bbox_inches='tight')
        # fig_nir = s2_stack.plot_false_color_infrared()
        # fig_nir.savefig(fname=fname_nir, bbox_inches='tight')
        # fig_scl = s2_stack.plot_scl()
        # fig_scl.savefig(fname=fname_scl, bbox_inches='tight')

        # read Vegetation parameter/index band
        handler = SatDataHandler()
        handler.read_from_bandstack(
            fname_bandstack=Path(record.filename_veg_par),
            in_file_aoi=in_file_aoi,
            full_bounding_box_only=True
        )
        handler.reset_bandnames(new_bandnames=[vi_name])
        fig_vi = handler.plot_band(band_name=vi_name, colormap='summer')
        fig_vi.savefig(fname=fname_vi, bbox_inches='tight')
        s2_stack.add_band(
            band_name=vi_name,
            band_data=handler.get_band(vi_name),
            snap_band='B02'
        )
        # save the file path to dict
        orig_vi_dict[record.date] = Path(record.filename_veg_par)

        # read vegetation parameter/index uncertainty band
        handler = SatDataHandler()
        handler.read_from_bandstack(
            fname_bandstack=Path(record.filename_unc),
            in_file_aoi=in_file_aoi,
            band_selection=['abs_stddev'],
            full_bounding_box_only=True
        )

        # fig_unc = handler.plot_band(
        #     band_name='abs_stddev'
        # )
        # fig_unc.savefig(fname=fname_unc, bbox_inches='tight')

        # apply the cloud mask also to the absolute uncertainty band
        s2_stack.add_band(
            band_name=f'{vi_name}_unc',
            band_data=handler.get_band('abs_stddev'),
            snap_band='B02'
        )
        unc_dict[record.date] = Path(record.filename_unc)

        # mask clouds, shadows, cirrus, dark area and unclassified pixels using the
        # information in the scene classification layer
        s2_stack.mask_clouds_and_shadows(
            bands_to_mask=[vi_name, f'{vi_name}_unc'],
            cloud_classes=[2,3,7,8,9,10]
        )

        update_list.append({
            'date': record.date,
            'cloudy_pixel_percentage': cloud_coverage
        })

        bands_to_drop = ['B02','B03','B04','B08','SCL']
        for band_to_drop in bands_to_drop:
            s2_stack.drop_band(band_to_drop)
        ts_stack_dict[record.date] = s2_stack

    # added update columns to input data frame
    update_df = pd.DataFrame(update_list)
    merged = pd.merge(data_df, update_df, on='date')

    # backup met
    merged.to_csv(out_dir_plots.joinpath('metadata.csv'), index=False)

    return merged, ts_stack_dict, orig_vi_dict, unc_dict


def extract_uncertainty_crops(
        file_df: pd.DataFrame,
        ts_stack_dict: Dict[date, SatDataHandler],
        sample_polygons: Path,
        vi_name: str,
        out_dir: Path,
        ymin: float,
        ymax: float
    ) -> None:
    """
    Extracts the uncertainty information for the field parcel polygons.

    """

    # loop over scenes, rasterize the shapefile with the crops and convert it to
    # geodataframe to allow for crop-type specific analysis
    gdf_dict = {}
    for idx, record in file_df.iterrows():

        # read original (reference) data for the field polygons
        _date = record.date
        scene_handler = deepcopy(ts_stack_dict[_date])

        scene_handler.add_bands_from_vector(
            in_file_vector=sample_polygons,
            snap_band=vi_name,
            attribute_selection=['crop_code']
        )

        # convert to geodataframe and save them as CSVs
        gdf = scene_handler.to_dataframe()
        # drop NaNs
        gdf = gdf.dropna()
        gdf['date'] = record.date
        fname_csv = out_dir.joinpath(f'{vi_name}_{idx+1}_crops.csv')
        gdf_dict[date] = fname_csv
        scene_handler = None
        gdf.to_csv(fname_csv, index=False)
        logger.info(f'Read scene data from {_date} ({idx+1}/{file_df.shape[0]})')

    # concat dataframes (fails unfortunately)
    # gdf = pd.concat(gdf_list)
    # gdf.to_csv(out_dir.joinpath(f'{vi_name}_crops.csv'), index=False)

    # add crop name from original shape file
    gdf_polys = gpd.read_file(sample_polygons)

    # loop over crop types and plot their VI curve and its uncertainty over time
    crop_codes, pixel_counts = np.unique(gdf.crop_code, return_counts=True)

    for crop_code, pixel_count in list(zip(crop_codes, pixel_counts)):

        # get crop name
        crop_name = gdf_polys[gdf_polys.crop_code == int(crop_code)]['crop_type'].iloc[0]

        # get values
        gdf_list = []
        for _date in file_df.date.unique():
            gdf_date = pd.read_csv(gdf_dict[_date])
            crop_gdf = gdf_date[gdf_date.crop_code == crop_code].copy()
            # aggregate by date
            crop_gdf_grouped = crop_gdf[['date', vi_name, f'{vi_name}_unc']].groupby('date').agg(
                ['mean', 'min', 'max', 'std']
            )
            gdf_list.append(crop_gdf)

        crop_gdf = pd.concat(gdf_list)

        # plot
        fig, (ax1, ax2) = plt.subplots(2, sharex=True, figsize=(15,10))

        # plot original time series showing spread between pixels (not scenarios!)
        ax1.plot(crop_gdf_grouped[vi_name, 'mean'], color='blue', linewidth=3)
        ax1.fill_between(
            x=crop_gdf_grouped.index,
            y1=crop_gdf_grouped[vi_name, 'min'],
            y2=crop_gdf_grouped[vi_name, 'max'],
            color='orange',
            alpha=0.4
        )
        ax1.fill_between(
            x=crop_gdf_grouped.index,
            y1=crop_gdf_grouped[vi_name, 'mean']-crop_gdf_grouped[vi_name, 'std'],
            y2=crop_gdf_grouped[vi_name, 'mean']+crop_gdf_grouped[vi_name, 'std'],
            color='red',
            alpha=0.45
        )
        ax1.set_title({vi_name}, fontsize=20)
        ax1.set_ylabel(f'{vi_name} [-]', fontsize=24)
        ax1.set_ylim(ymin, ymax)

        # plot uncertainties
        unc_name = vi_name + '_unc'
        ax2.plot(crop_gdf_grouped[unc_name, 'mean'], label='Mean', color='blue', linewidth=3)
        ax2.fill_between(
            x=crop_gdf_grouped.index,
            y1=crop_gdf_grouped[unc_name, 'min'],
            y2=crop_gdf_grouped[unc_name, 'max'],
            color='orange',
            alpha=0.4,
            label='Min-Max Spread'
        )
        ax2.fill_between(
            x=crop_gdf_grouped.index,
            y1=crop_gdf_grouped[unc_name, 'mean']-crop_gdf_grouped[unc_name, 'std'],
            y2=crop_gdf_grouped[unc_name, 'mean']+crop_gdf_grouped[unc_name, 'std'],
            color='red',
            alpha=0.45,
            label=r'$\pm$ Stddev'
        )
        ax2.set_title(f'Uncertainty in {vi_name}', fontsize=20)
        ax2.set_ylabel(f'Absolute Uncertainty [-]', fontsize=24)
        ax2.legend(loc="lower center", bbox_to_anchor=(0.5, -0.5), fontsize=20, ncol=3)

        fig.suptitle(f'Time Series of {crop_name} (Pixels: {pixel_count})', fontsize=26)
        fname = f'{vi_name}_{crop_name}_all-pixel-timeseries.png'
        fig.savefig(out_dir.joinpath(fname), dpi=300, bbox_inches='tight')
        plt.close(fig)
        


def vegetation_time_series_scenarios(
        ts_stack_dict: Dict[date, Sentinel2Handler],
        orig_vi_dict: Dict[date, Path],
        unc_dict: Dict[date, Path],
        n_scenarios: int,
        out_dir_scenarios: Path,
        vi_name: str,
        sample_points: Path
    ) -> None:
    """
    Generates the vegetation time series scenarios applying the uncertainty
    in the vegetation parameter/indices. The time series are processed in a
    similar manner TIMESAT does, using the ``Phenolopy`` package.

    To ensure the time series results are meaningful, pixel time series are
    extracted for a selected number of point features specified
    by an ESRI shapefile of point features containing information about the
    underlying crop type. A CSV file containing the extracted pixel time series
    (original data + smoothed time series from scenarios) is written to
    ``out_dir_scenarios``.

    :param ts_stack_dict:
        dictionary with ``SatDataHandler`` instances holding the vegetation parameter
        as one band and its uncertainty as another band per scene date
    :param orig_vi_dict:
        dictionary with the original (reference) vegetation index/parameter values
    :param unc_dict:
        dictionary with the uncertainty images of the vegetation index/parameter
    :param n_scenarios:
        number of scenarios to generate
    :param out_dir_scenarios:
        directory where to save the results of the scenario runs to
    :param vi_name:
        name of the vegetation parameter/index
    :param dates:
        list of dates. Must equal the length of the ``ts_stack_list``. Is used
        to assign a date to each handler to construct the time series.
    :param sample_points:
        shapefile with points to use for time series pixels samples. The extracted
        time series are plotted and saved to a sub-directory called 'pixel_plots'
    """

    # get coordinates for xarray dataset
    coords = ts_stack_dict[list(ts_stack_dict.keys())[0]].get_coordinates(vi_name)
    dates = ts_stack_dict.keys()
    dates_np = [np.datetime64(x) for x in dates]
    coords.update({'time': dates_np})

    # add stack atttributes for xarray dataset
    attrs = {}
    crs = ts_stack_dict[list(ts_stack_dict.keys())[0]].get_epsg(vi_name)
    attrs['crs'] = crs
    attrs['transform'] = tuple(ts_stack_dict[list(ts_stack_dict.keys())[0]].get_meta(vi_name)['transform'])

    # calculate the x and y array indices required to extract the pixel values
    # at the sample locations from the array holding the smoothed vegetation
    gdf_points = gpd.read_file(sample_points)
    gdf_points['x'] = gdf_points.geometry.x
    gdf_points['y'] = gdf_points.geometry.y

    # map the coordinates to array indices
    def find_nearest_array_index(array, value):
        return np.abs(array - value).argmin()
    # get column (x) indices
    gdf_points['col'] = gdf_points['x'].apply(
        lambda x, coords=coords, find_nearest_array_index=find_nearest_array_index:
        find_nearest_array_index(coords['x'], x)
    )
    # get row (y) indices
    gdf_points['row'] = gdf_points['y'].apply(
        lambda y, coords=coords, find_nearest_array_index=find_nearest_array_index:
        find_nearest_array_index(coords['y'], y)
    )

    # loop over the scenarios. In each scenario run generate a xarray containing vegetation
    # index/parameter samples order by date (i.e., the xarray dataset is 3-dimensional: x,y,time)
    # save the calculated Pheno-metrics by the end of each scenario run to a raster file
    orig_ts_list = []
    for scenario in range(n_scenarios):

        logger.info(f'Running scenario ({scenario+1}/{n_scenarios})')
        # add vegetation samples to 3d numpy array and pass it to xarray dataset
        sample_list = []
        gdf_list = []
        for _date in list(dates):
            vi_data = ts_stack_dict[_date].get_band(vi_name).data
            vi_unc = ts_stack_dict[_date].get_band(f'{vi_name}_unc').data

            # sample the test points
            # sample original pixel values only in first scenario run
            if scenario == 0:
                vegpar_file = orig_vi_dict[_date]
                # TODO: sample from array directly to avoid potential shifts
                gdf_sample_data = SatDataHandler.read_pixels(
                    point_features=sample_points,
                    raster=vegpar_file
                )
                colnames = list(gdf_sample_data.columns)
                if None in colnames:
                    colnames[colnames.index(None)] = vi_name
                gdf_sample_data.columns = colnames
                
                vegpar_unc = unc_dict[_date]
            
                gdf_sample_unc = SatDataHandler.read_pixels(
                    point_features=sample_points,
                    raster=vegpar_unc,
                    band_selection=['abs_stddev']
                )
                gdf_sample_unc.rename({'abs_stddev': 'unc'}, axis=1, inplace=True)

                # join the data frames
                gdf = pd.merge(
                    gdf_sample_data[['id', 'crop_type', 'geometry', vi_name]],
                    gdf_sample_unc[['id', 'unc']],
                    on='id'
                )
                gdf['date'] = _date
                # join row and column
                gdf_joined = pd.merge(
                    gdf,
                    gdf_points[['id', 'row', 'col']],
                    on='id'
                )
                
                gdf_list.append(gdf_joined)

                # append original raster data to stack once
                orig_ts_list.append(vi_data)

            # get samples from uncertainty distribution and add it to the vi_data
            # (can be done directly because we deal with absolute uncertainties)
            samples = np.random.normal(
                loc=0,
                scale=vi_unc,
                size=vi_data.shape
            )
            samples += vi_data
            sample_list.append(samples)

        # create the 3d numpy array to pass as xarray dataset
        stack = {'veg_index': tuple([('y','x','time'), np.dstack(sample_list)])}

        # create stack for the reference run and the pixel time series of the reference
        # data (do it in the first iteration only to avoid overwritten the data again and
        # again)
        if scenario == 0:
            orig_stack = {'veg_index': tuple([('y','x','time'), np.dstack(orig_ts_list)])}
            gdf = pd.concat(gdf_list)

        # construct xarray dataset for the scenario run
        try:
            xds = xr.Dataset(
                stack,
                coords=coords,
                attrs=attrs
            )
            res = _calc_pheno_metrics(xds)
            pheno_ds = res['pheno_metrics'] # pheno metric results
            ds = res['ds'] # smoothed time series values
        except Exception as e:
            logger.error(f'Error in scenario ({scenario+1}/{n_scenarios}): {e}')

        # get the smoothed time series values from the dataset at the sample locations
        # unfortunately, there seems to be no ready-to-use solution
        unique_points = gdf[gdf.date == gdf.date.unique()[0]][['id', 'row', 'col']]

        scenario_col = f'{vi_name}_{scenario+1}'
        gdf[scenario_col] = np.empty(gdf.shape[0])
        # loop over sample points and add them as new entries to the dataframe
        for _, unique_point in unique_points.iterrows():
            ts_values = ds[dict(x=[unique_point.col], y=[unique_point.row])]['veg_index'].data
            gdf.loc[
                (gdf.row == unique_point.row) & (gdf.col == unique_point.col) & (gdf.id == unique_point.id),
                scenario_col
            ] = ts_values[0,0,:]

        # do the same for the reference run
        if scenario == 0:
            try:
                # TODO: SCL masking it missing here!!!!
                xds_ref = xr.Dataset(
                    orig_stack,
                    coords=coords,
                    attrs=attrs
                )
                res_ref = _calc_pheno_metrics(xds_ref)
                pheno_ds_ref = res_ref['pheno_metrics'] # pheno metric results
                ds_ref = res_ref['ds'] # smoothed time series values
            except Exception as e:
                logger.error(f'Error in reference run: {e}')

            ref_col = f'{vi_name}_ts_sm'
            gdf[ref_col] = np.empty(gdf.shape[0])
            # loop over sample points and add them as new entries to the dataframe
            for _, unique_point in unique_points.iterrows():
                ts_values = ds_ref[dict(x=[unique_point.col], y=[unique_point.row])]['veg_index'].data
                gdf.loc[
                    (gdf.row == unique_point.row) & (gdf.col == unique_point.col) & (gdf.id == unique_point.id),
                    ref_col
                ] = ts_values[0,0,:]

        # save to raster files using the SatDataHandler object since it has the full geoinformation
        # available
        pheno_handler = deepcopy(ts_stack_dict[list(ts_stack_dict.keys())[0]])
        pheno_metrics = [
            'sos_values', 'sos_times', 'pos_values', 'pos_times', 'eos_values', 'eos_times'
        ]

        out_dir_scenario = out_dir_scenarios.joinpath(str(scenario+1))
        if not out_dir_scenario.exists():
            out_dir_scenario.mkdir()
        out_file = out_dir_scenario.joinpath('pheno_metrics.tif')

        for pheno_metric in pheno_metrics:
            pheno_handler.add_band(
                band_name=pheno_metric,
                band_data=eval(f'pheno_ds.{pheno_metric}.data'),
                snap_band=vi_name
            )

        # remove "template" files
        bands_to_drop = [vi_name, f'{vi_name}_unc']
        for band_to_drop in bands_to_drop:
            pheno_handler.drop_band(band_to_drop)

        # save to geoTiff
        pheno_handler.write_bands(out_file)

        # write original data
        if scenario == 0:
            pheno_handler = None
            pheno_handler = deepcopy(ts_stack_dict[list(ts_stack_dict.keys())[0]])
        
            out_dir_scenario = out_dir_scenarios.joinpath('reference')
            if not out_dir_scenario.exists():
                out_dir_scenario.mkdir()
            out_file = out_dir_scenario.joinpath('pheno_metrics.tif')

            for pheno_metric in pheno_metrics:
                pheno_handler.add_band(
                    band_name=pheno_metric,
                    band_data=eval(f'pheno_ds_ref.{pheno_metric}.data'),
                    snap_band=vi_name
                )

            # remove "template" files
            bands_to_drop = [vi_name, f'{vi_name}_unc']
            for band_to_drop in bands_to_drop:
                pheno_handler.drop_band(band_to_drop)

            # save to geoTiff
            pheno_handler.write_bands(out_file)

        logger.info(f'Finished scenario ({scenario+1}/{n_scenarios})')

    # save sample points to CSV (can be used for analyzing pixel time series)
    fname_csv = out_dir_scenarios.joinpath(
        f'{vi_name}_{sample_points.name}_pixel_time_series.csv'
    )
    gdf['date'] = gdf['date'].apply(lambda x: x.strftime('%Y-%m-%d'))
    gdf['x'] = gdf.geometry.x
    gdf['y'] = gdf.geometry.y
    gdf.drop('geometry', axis=1, inplace=True)
    gdf.to_csv(fname_csv, index=False)


def main(
        vi_dir: Path,
        uncertainty_analysis_dir: Path,
        in_file_aoi: Path,
        out_dir_scenarios: Path,
        out_dir_plots: Path,
        n_scenarios: int,
        vi_name: str,
        sample_points: Path,
        sample_polygons: Path,
        ymin: float,
        ymax: float
    ):
    """
    main executable function of this module generating the scenarios for the
    phenological metrics based on the uncertainty in the underlying vegetation
    indices/ parameters calculated in the previous step.
    """

    # search files, join and order them by date
    data_df = get_data_and_uncertainty_files(
        vi_dir=vi_dir,
        uncertainty_analysis_dir=uncertainty_analysis_dir,
        vi_name=vi_name
    )

    # read the data and mask clouds, shadows, and unclassified pixels based on SCL information
    file_df, ts_stack_dict, orig_vi_dict, unc_dict = read_data_and_uncertainty(
        data_df=data_df,
        vi_name=vi_name,
        in_file_aoi=in_file_aoi,
        out_dir_plots=out_dir_plots
    )

    # check uncertainty in different crop types over time
    extract_uncertainty_crops(
        file_df=file_df,
        ts_stack_dict=ts_stack_dict,
        sample_polygons=sample_polygons,
        out_dir=out_dir_scenarios,
        vi_name=vi_name,
        ymin=ymin,
        ymax=ymax
    )

    # actual phenological metrics scenarios
    # vegetation_time_series_scenarios(
    #     ts_stack_dict=ts_stack_dict,
    #     orig_vi_dict=orig_vi_dict,
    #     unc_dict=unc_dict,
    #     n_scenarios=n_scenarios,
    #     out_dir_scenarios=out_dir_scenarios,
    #     vi_name=vi_name,
    #     sample_points=sample_points
    # )


if __name__ == '__main__':
    # original Sentinel-2 scenes with vegetation indices
    vi_dir = Path(
        '../S2A_MSIL1C_orig/*.VIs'
    )
    
    # directory with uncertainty analysis results
    uncertainty_analysis_dir = Path(
        '../S2A_MSIL2A_Analysis/150_scenarios'
    )

    # extent of study area
    in_file_aoi = Path(
        '../shp/AOI_Esch_EPSG32632.shp'
    )

    # define sample polygons (for visualizing the uncertainty per crop type over time)
    sample_polygons = Path('../shp/ZH_Polygons_2019_EPSG32632_selected-crops_buffered.shp')

    # define point sampling locations for visualizing pixel time series
    sample_points = Path('../shp/ZH_Points_2019_EPSG32632_selected-crops.shp')

    # vegetation index to consider
    vi_names = ['NDVI','EVI']
    ymins = {'NDVI': 0, 'EVI': 0}
    ymaxs = {'NDVI': 1, 'EVI': 1}

    # directory where to save phenological metrics to
    out_dir_scenarios = Path(f'../S2_TimeSeries_Analysis')
    if not out_dir_scenarios.exists():
        out_dir_scenarios.mkdir()

    # directory where to save plots to
    out_dir_plots = uncertainty_analysis_dir.joinpath('scene_quicklooks')
    if not out_dir_plots.exists():
        out_dir_plots.mkdir()
    
    # number of scenarios to generate
    n_scenarios = 1000

    for vi_name in vi_names:

        out_dir_scenarios_vi = out_dir_scenarios.joinpath(vi_name)
        if not out_dir_scenarios_vi.exists():
            out_dir_scenarios_vi.mkdir()

        main(
            vi_dir=vi_dir,
            uncertainty_analysis_dir=uncertainty_analysis_dir,
            in_file_aoi=in_file_aoi,
            out_dir_scenarios=out_dir_scenarios_vi,
            out_dir_plots=out_dir_plots,
            n_scenarios=n_scenarios,
            vi_name=vi_name,
            sample_points=sample_points,
            sample_polygons=sample_polygons,
            ymin=ymins[vi_name],
            ymax=ymaxs[vi_name]
        )
