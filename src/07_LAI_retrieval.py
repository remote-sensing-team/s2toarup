'''
While the actual LAI retrieval is carried out in Matlab this script does some
post-processing on the output of the Matlab routine. This includes clipping of
the data to the extent of the study area, renaming of the file and renaming of
the band names.
'''

import os
import shutil
import sys
import glob
import shlex
from subprocess import Popen, PIPE
from pathlib import Path
from typing import Optional

from agrisatpy.io import SatDataHandler
from logger import get_logger

logger = get_logger('07_LAI_retrieval')


def loop_orig_datasets(
        orig_dataset_dir: Path,
        shapefile_study_area: Path,
        model_path: Path,
        matlab_compiled_script_path: Path,
        matlab_runtime_path: Path,
    ):
    """
    Loops over the original S2 scenes found and runs the LAI model
    developed by Amin et al. (2021, RSE) on each dataset. To keep the
    disk space requirements as low as possible and to stay conform with
    file naming conventions, also renames the outputs of the LAI routine.

    :param orig_dataset_dir:
        directory where the original S2 scenes are stored
    :param shapefile_study_area:
        ESRI shapefile denoting the extent of the study area (used for
        clipping output of LAI model)
    :param lai_model_path:
        path to the actual LAI model (*.mat file) from Amin et al. (2021)
    :param matlab_compiled_script_path:
        path to the compiled matlab script compiled from the original
        Matlab code from Amin et al. (2021).
    :param matlab_runtime_path:
        path to the Matlab runtime root directory
    """

    # define temporary output directory
    out_dir = orig_dataset_dir.joinpath('temp_lai')
    out_dir.mkdir(exist_ok=True)

    # call LAI model here (using subprocess)
    cwd = os.getcwd()
    # change into directory where the Matlab src is located to avoid path problems
    os.chdir(matlab_compiled_script_path.parent)
    matlab_script = matlab_compiled_script_path.name
    # cmd_inp = f'{matlab_executable_path} -nodisplay -nosplash -r "{matlab_script} {model_path} {in_dir_safe} {out_dir}"'
    cmd_inp = f'./{matlab_script} {matlab_runtime_path} {model_path} {orig_dataset_dir} {out_dir}'

    command = shlex.split(cmd_inp)
    process = Popen(command, stdout=PIPE, stderr=PIPE)
    _, stderr = process.communicate()

    if stderr != b'':
        logger.error(f'Execution of LAI retrieval errored: {stderr}')
        sys.exit()

    # change back into previous working directory
    os.chdir(cwd)

    # once the model is finished, apply the post-processing
    lai_products = glob.glob(out_dir.joinpath('LAI_S2*.tiff').as_posix())
    logger.info(f'Finished LAI retrieval')

    for lai_product in lai_products: 
        post_process_lai_product(
            lai_product=Path(lai_product),
            shapefile_study_area=shapefile_study_area,
            plot_product=True
        )
    
    # copy the files into the correct destination folder
    lai_tifs = glob.glob(out_dir.joinpath('*LAI.tif').as_posix())
    
    for lai_tif in lai_tifs:
    
        date_str = Path(lai_tif).name.split('_')[1]
        search_expr = orig_dataset_dir.joinpath(f'S2*_{date_str}T*.VIs').as_posix()
        dst = Path(glob.glob(search_expr)[0]).joinpath('Vegetation_Indices')
        shutil.move(lai_tif, dst)

    

def loop_scenarios(
        scenario_dir: Path,
        shapefile_study_area: Path,
        model_path: Path,
        matlab_compiled_script_path: Path,
        matlab_runtime_path: Path,
    ):
    """
    Loops over the scenarios of all S2 scenes found and runs the LAI model
    developed by Amin et al. (2021, RSE) on each scenario run. To keep the
    disk space requirements as low as possible and to keep conform with
    file naming conventions, also renames the outputs of the LAI routine.

    :param scenario_dir:
        directory where the S2 scenes and their scenario runs are stored
    :param shapefile_study_area:
        ESRI shapefile denoting the extent of the study area (used for
        clipping output of LAI model)
    :param lai_model_path:
        path to the actual LAI model (*.mat file) from Amin et al. (2021)
    :param matlab_compiled_script_path:
        path to the compiled matlab script compiled from the original
        Matlab code from Amin et al. (2021).
    :param matlab_runtime_path:
        path to the Matlab runtime root directory
    """

    # find scenes for which scenarios are available
    scenes = glob.glob(scenario_dir.joinpath('S2*_MSIL1C*').as_posix())

    # loop over scenes and their scenarios
    for idx, scene in enumerate(scenes):

        logger.info(f'Working on scene {scene} ({idx+1}/{len(scenes)})')

        # find L2A scenes
        scenarios = glob.glob(Path(scene).joinpath('*/S2*_MSIL2A*.SAFE').as_posix())

        # loop over scenarios of the current scene
        for jdx, scenario in enumerate(scenarios):

            # define input and outputs for the LAI model
            scenario = Path(scenario)
            in_dir_safe = scenario.parent.as_posix()
            vi_dir = scenario.parent.joinpath('Vegetation_Indices')
            out_dir = vi_dir.as_posix()

            logger.info(f'Starting LAI retrieval {jdx+1}/{len(scenarios)} ({scenario})')
            # call LAI model here (using subprocess)
            cwd = os.getcwd()
            # change into directory where the Matlab src is located to avoid path problems
            os.chdir(matlab_compiled_script_path.parent)
            matlab_script = matlab_compiled_script_path.name
            # cmd_inp = f'{matlab_executable_path} -nodisplay -nosplash -r "{matlab_script} {model_path} {in_dir_safe} {out_dir}"'
            cmd_inp = f'./{matlab_script} {matlab_runtime_path} {model_path} {in_dir_safe} {out_dir}'

            command = shlex.split(cmd_inp)
            process = Popen(command, stdout=PIPE, stderr=PIPE)
            _, stderr = process.communicate()

            if stderr != b'':
                logger.error(f'Execution of LAI retrieval errored: {stderr}')
                sys.exit()

            # change back into previous working directory
            os.chdir(cwd)

            # once the model is finished, apply the post-processing
            lai_product = glob.glob(vi_dir.joinpath('LAI_S2*.tiff').as_posix())[0]
            logger.info(f'Finished LAI retrieval {jdx+1}/{len(scenarios)} ({scenario})')

            post_process_lai_product(
                lai_product=Path(lai_product),
                shapefile_study_area=shapefile_study_area
            )

            logger.info(f'Cleaned up LAI outputs {jdx+1}/{len(scenarios)} ({scenario})')

        logger.info(f'Finished scene {scene} ({idx+1}/{len(scenes)})')

    logger.info('Done')


def post_process_lai_product(
        lai_product: Path,
        shapefile_study_area: Path,
        plot_product: Optional[bool] = False
    ) -> None:
    """
    Applies post-processing to the output of the LAI model by Amin et al. (2021)
    including clipping of the output file to the extent of the study area to save
    disk space and applying the naming convention from the NDVI and EVI products.

    :param lai_product:
        file-path to the LAI product (geoTiff) with three bands. The first band
        contains the actual LAI estimate, the second the standard deviation (GPR
        uncertainty) and the third the coefficient of variation.
    :param shapefile_study_area:
        ESRI shapefile denoting the extent of the study area (used for
        clipping output of LAI model)
    :param plot_product:
        plotting of the LAI results. Disabled by default to avoid performance losses.
    """

    # save output to the same directory where the LAI product is placed
    out_dir = lai_product.parent

    handler = SatDataHandler()
    # read output of LAI routine
    handler.read_from_bandstack(
        fname_bandstack=lai_product,
        in_file_aoi=shapefile_study_area
    )

    # rename bands
    new_bandnames = ['LAI', 'SD', 'CV']
    handler.reset_bandnames(new_bandnames)

    # plot bands (demo only)
    if plot_product:
        labels = [
            r'Leaf Area Index [$m^2/m^2$]',
            r'Standard Deviation [$m^2/m^2$]',
            'Coefficient of Variation [%]'
        ]
        cmaps = ['YlGn', 'Oranges', 'Oranges']
        for idx, band_name in enumerate(new_bandnames):
            ymin, ymax = None, None
            if band_name == 'CV':
                ymin, ymax = 0, 100
            fig_lai = handler.plot_band(
                band_name=band_name,
                colormap=cmaps[idx],
                colorbar_label=labels[idx],
                vmin=ymin,
                vmax=ymax
            )
            fname = out_dir.joinpath(f'{lai_product.name}_{band_name}.png')
            fig_lai.savefig(fname, dpi=300, bbox_inches='tight')

    # save raster as geoTiff applying the same naming convention as for the NDVI and EVI
    fname_lai_splitted = lai_product.name.split('.')[0].split('_')
    lai_str = fname_lai_splitted[0]
    sensor_str = fname_lai_splitted[1]
    date_tile_str = fname_lai_splitted[2] + '_' + fname_lai_splitted[3]
    fname_out = out_dir.joinpath(
        f'VI_{date_tile_str}_MSIL2A_{sensor_str}_None_10m_{lai_str}.tif'
    )
    handler.write_bands(out_file=fname_out)

    # remove the original LAI product to save disk space
    os.remove(lai_product)
    # remove README.txt to keep runs clean
    os.remove(out_dir.joinpath(lai_product.name.replace('.tiff', '_README.txt')))


if __name__ == '__main__':

    # input directories and files
    scenario_dir = Path('/home/graflu/public/Evaluation/Projects/KP0031_lgraf_PhenomEn/Uncertainty/ESCH/scripts_paper_uncertainty/S2A_MSIL1C_RUT-Scenarios')
    shapefile_study_area = Path('/mnt/ides/Lukas/software/scripts_paper_uncertainty/shp/AOI_Esch_EPSG32632.shp')
    orig_dataset_dir = Path('/home/graflu/public/Evaluation/Projects/KP0031_lgraf_PhenomEn/Uncertainty/ESCH/scripts_paper_uncertainty/S2A_MSIL1C_orig')

    # LAI model path
    gpr_install_dir = Path('/home/graflu/git/s2gpr_ret')
    lai_model_path = gpr_install_dir.joinpath('LAIGreen_GPR_10b_4k_v11_1.mat')

    # path to the sh file calling the compiled Matlab application
    matlab_compiled_script_path = gpr_install_dir.joinpath(
        'S2Ret_run/for_redistribution_files_only/run_S2Ret_run.sh'
    )
    
    # path to the Matlab executable (not required if matlab is found in $PATH)
    matlab_runtime_path = Path('/home/graflu/MATLAB/v911')

    # process original datasets
    loop_orig_datasets(
        orig_dataset_dir=orig_dataset_dir,
        shapefile_study_area=shapefile_study_area,
        model_path=lai_model_path,
        matlab_compiled_script_path=matlab_compiled_script_path,
        matlab_runtime_path=matlab_runtime_path
    )

    # process scenario data
    loop_scenarios(
        scenario_dir=scenario_dir,
        shapefile_study_area=shapefile_study_area,
        model_path=lai_model_path,
        matlab_compiled_script_path=matlab_compiled_script_path,
        matlab_runtime_path=matlab_runtime_path
    )
