'''
Plots kernel-density estimates of the uncertainty values in the LSP metrics.
'''

from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

plt.style.use('ggplot')


if __name__ == '__main__':

    lsp_res_dir = Path(
        '../../S2_TimeSeries_Analysis'
    )

    vis = ['EVI', 'NDVI', 'GLAI']
    runs = ['uncorrelated', 'fully_correlated']
    metrics = ['sos_times', 'eos_times', 'length_of_season']

    # read all data into a large data frame
    for metric in metrics:
        f, axes = plt.subplots(nrows=2, ncols=3, figsize=(15,8))
        for vidx, vi in enumerate(vis):
            for rdx, run in enumerate(runs):
                search_path = lsp_res_dir.joinpath(f'{vi}/{run}/Uncertainty_Maps/selected_crops')
                fpath = next(search_path.glob(f'{vi}_{metric}_*_data.csv'))
                df = pd.read_csv(fpath)

                # correct stupid typos and rename some crops
                df['crop'] = df['crop'].apply(lambda x: 'Rapeseed' if x == 'Canola' else x)
                df['crop'] = df['crop'].apply(lambda x: 'Grain Maize' if x == 'Corn' else x)
                df['crop'] = df['crop'].apply(lambda x: 'Permament Grassland' if x == 'Permament Grasland' else x)
                df['crop'] = df['crop'].apply(lambda x: 'Extensively Used Grassland' if x == 'Extensively Used Grasland' else x)

                # sns.boxplot(x='crop', y=f'{metric} Uncertainty', data=df, ax=axes[rdx,vidx])
                sns.kdeplot(x=f'{metric} Uncertainty', hue='crop', data=df, ax=axes[rdx,vidx],
                            fill=True, alpha=.5, multiple='stack')
                axes[rdx,vidx].set_xlim(0,100)
                axes[rdx,vidx].set_ylim(0,.1)
                if vidx != 2 or rdx != 1:
                    axes[rdx,vidx].get_legend().remove()
                else:
                    pass

                if vidx == 0 and rdx == 0:
                    axes[rdx,vidx].set_ylabel('Zero Scene Correlation', fontsize=14)
                if vidx == 0 and rdx == 1:
                    axes[rdx,vidx].set_ylabel('Full Scene Correlation', fontsize=14)
                if rdx == 1:
                    label = metric.split('_')[0].upper() + ' Uncertainty (k=1) [days]'
                    if metric == 'length_of_season':
                        label = 'LOS Uncertainty (k=1) [days]'
                    axes[rdx,vidx].set_xlabel(
                        label,
                        fontsize=14,
                        # rotation=270,
                        labelpad=14
                    )
                if vidx == 2:
                    axes[rdx,vidx].yaxis.set_label_position("right")
                    axes[rdx,vidx].yaxis.tick_right()

                # if vidx == 0 and rdx == 1:
                    # axes[rdx,vidx].set_title(r'(b)', fontsize=22, loc='left')
                if rdx == 0:
                    axes[rdx,vidx].set_xlabel('')
                    axes[rdx,vidx].xaxis.set_ticklabels([])
                    axes[rdx,vidx].xaxis.set_ticks_position('none')
                    axes[rdx,vidx].title.set_text(vi)
                if rdx == 1:
                    plt.setp(axes[rdx,vidx].get_xticklabels(), rotation=90)
                if vidx == 1:
                    axes[rdx,vidx].set_ylabel('')
                    axes[rdx,vidx].yaxis.set_ticklabels([])
                    axes[rdx,vidx].yaxis.set_ticks_position('none')


        fpath_fig = lsp_res_dir.joinpath(f'{metric}_uncertainty.png')
        f.savefig(fpath_fig, dpi=300, bbox_inches='tight')
