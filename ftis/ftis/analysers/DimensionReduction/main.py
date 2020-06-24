import os
import umap, time
import numpy as np
from alive_progress import alive_bar
from ftis.common.analyser import FTISAnalyser
from ftis.common.utils import read_json, write_json
from ftis.common.types import Ftypes
from sklearn.preprocessing import MinMaxScaler, StandardScaler


class DimensionReduction(FTISAnalyser):
    def __init__(self, config):
        super().__init__(config)
        self.name = "DimensionReduction"
        self.input_type = Ftypes.json
        self.output_type = Ftypes.json

    def run(self):
        with alive_bar(1, spinner='dots_waves') as bar:
            bar()
            print("Doing some dimension reduction")
            analysis_data = read_json(self.input)
            data = [v for v in analysis_data.values()]
            keys = [k for k in analysis_data.keys()]

            if self.parameters["scaling"] == "normalise":
                scaler = MinMaxScaler()
            if self.parameters["scaling"] == "standardise":
                scaler = StandardScaler()
            
            data = np.array(data)
            data = scaler.fit_transform(data)

            # Fit the transform
            reduction = umap.UMAP(
                n_components=self.parameters["components"],
                n_neighbors=self.parameters["neighbours"],
                min_dist=self.parameters["mindist"]
            )
            data = reduction.fit_transform(data)

            # Normalisation
            if self.parameters["post_scaling"] == "normalise":
                post_scaling = MinMaxScaler()
            if self.parameters["post_scaling"] == "standardise":
                post_scaling = StandardScaler()
            if self.parameters["post_scaling"] != "none":
                data = post_scaling.fit_transform(data)

            dictionary_format_data = {}

            for key, value in zip(keys, data):
                dictionary_format_data[key] = value.tolist()
            
            write_json(self.output, dictionary_format_data)