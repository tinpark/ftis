import numpy as np
import hdbscan, math
from ftis.common.analyser import FTISAnalyser
from ftis.common.utils import read_json, write_json, samps2ms
from ftis.common.types import Ftypes
from ftis.common.proc import staticproc, multiproc, singleproc
from ftis.common.exceptions import NotYetImplemented
from sklearn.preprocessing import MinMaxScaler, StandardScaler
from sklearn.cluster import AgglomerativeClustering
from multiprocessing import Manager
from pathlib import Path
from untwist import transforms, data
from flucoma import fluid
from flucoma.utils import get_buffer, cleanup
from pydub import AudioSegment
from pydub.utils import mediainfo
from scipy.io import wavfile
from scipy import stats
from scipy.signal import savgol_filter


class Stats(FTISAnalyser):
    """Get various statistics and derivatives of those"""

    def __init__(self):
        super().__init__()
        self.numderivs = 0
        self.flatten = True

    def dump(self):
        write_json(self.dump_path, dict(self.buffer))

    @staticmethod
    def calc_stats(data):
        """Given a time series calculate statistics"""
        describe = stats.describe(data)
        mean = describe.mean
        stddev = math.sqrt(describe.variance)
        skewness = describe.skewness
        kurtosis = describe.kurtosis
        minimum = describe.minmax[0]
        median = np.median(data)
        maximum = describe.minmax[1]
        return [mean, stddev, skewness, kurtosis, minimum, median, maximum]

    def get_stats(self, base_data, num_derivs: int) -> list:
        """
        Given stats on n number derivatives from initial data
        """
        container = []
        if num_derivs > 0:
            for i in range(num_derivs):
                deriv = np.diff(base_data, i + 1)
                stats = self.calc_stats(deriv)
                container.append(stats)

        elif num_derivs <= 0:
            container = self.calc_stats(base_data)

        return container

    def analyse(self, workable):
        # TODO: any dimensionality input
        element_container = []
        values = np.array(self.input[workable])
        if len(values.shape) < 2:  # single row we run the stats on that
            element_container.append(self.get_stats(values, self.numderivs))
        else:
            for row in values:  # for mfcc band in mfcc
                element_container.append(self.get_stats(row, self.numderivs))

        if self.flatten:
            element_container = np.array(element_container)
            element_container = element_container.flatten()
            element_container = element_container.tolist()
        self.buffer[workable] = element_container

    def run(self):
        self.buffer = Manager().dict()
        workables = [x for x in self.input.keys()]
        singleproc(self.name, self.analyse, workables)
        self.output = dict(self.buffer)


class Flux(FTISAnalyser):
    """Computes spectral flux of an audio file"""

    def __init__(self):
        super().__init__()
        self.windowsize = 1024
        self.hopsize = 512

    def flux(self, workable):
        audio = data.Wave.read(str(workable))
        if audio.is_stereo():
            audio = np.sum(audio, axis=1)

        fft = transforms.STFT(fft_size=self.windowsize, hop_size=self.hopsize).process(
            audio
        )

        self.data[str(workable)] = list(
            np.sum(np.abs(np.diff(np.abs(fft))), axis=0)
        )  # this is the flux calculation here

    def dump(self):
        write_json(self.dump_path, dict(self.data))

    def run(self):
        self.data = Manager().dict()
        workables = [x for x in self.input.iterdir() if x.suffix == ".wav"]
        multiproc(self.name, self.flux, workables)
        self.output = dict(self.data)


class Normalise(FTISAnalyser):
    def __init__(self):
        super().__init__()
        self.min = 0
        self.max = 1

    def analyse(self):
        scaled_data = MinMaxScaler((self.min, self.max)).fit_transform(self.features)

        self.output = {}
        for k, v in zip(self.keys, scaled_data):
            self.output[k] = list(v)

    def dump(self):
        write_json(self.dump_path, self.output)

    def run(self):
        self.keys = [x for x in self.input.keys()]
        self.features = [x for x in self.input.values()]
        staticproc(self.name, self.analyse)


class Standardise(FTISAnalyser):
    def __init__(self):
        super().__init__()

    def analyse(self):
        scaled_data = StandardScaler().fit_transform(self.features)

        self.output = {}
        for k, v in zip(self.keys, scaled_data):
            self.output[k] = list(v)

    def dump(self):
        write_json(self.dump_path, self.output)

    def run(self):
        self.keys = [x for x in self.input.keys()]
        self.features = [x for x in self.input.values()]
        staticproc(self.name, self.analyse)


class ClusteredSegmentation(FTISAnalyser):
    def __init__(self):
        super().__init__()
        self.input_type = Ftypes.json
        self.output_type = Ftypes.json
        self.data_container = Manager().dict()

    def analyse(self, workable):
        slices = self.input_data[workable]
        slices = [int(x) for x in slices]  # lets test this out later
        count = 0
        standardise = StandardScaler()
        model = AgglomerativeClustering(n_clusters=self.parameters["numclusters"])

        while (count + self.parameters["windowsize"]) <= len(slices):
            indices = slices[
                count : count + self.parameters["windowsize"]
            ]  # create a section of the indices in question
            data = []
            for i, (start, end) in enumerate(zip(indices, indices[1:])):

                mfcc = fluid.mfcc(
                    workable,
                    fftsettings=[2048, -1, -1],
                    startframe=start,
                    numframes=end - start,
                )

                stats = get_buffer(fluid.stats(mfcc, numderivs=1), "numpy")

                data.append(stats.flatten())

            data = standardise.fit_transform(data)

            cluster = model.fit(data)
            cur = -2
            for j, c in enumerate(cluster.labels_):
                prev = cur
                cur = c
                if cur == prev:
                    try:
                        slices.pop(j + count)
                    except IndexError:
                        pass  # TODO fix later
            count += 1
            self.data_container[workable] = slices

    def run(self):
        self.input_data = read_json(self.input)
        workables = [str(k) for k in self.input_data]
        multiproc(self.name, self.analyse, workables)
        write_json(self.output, dict(self.data_container))


class UMAPDR(FTISAnalyser):
    """Dimension reduction with UMAP algorithm"""

    def __init__(self):
        super().__init__(config)
        self.input_type = Ftypes.json
        self.output_type = Ftypes.json

    def analyse(self):
        analysis_data = read_json(self.input)
        data = [v for v in analysis_data.values()]
        keys = [k for k in analysis_data.keys()]

        data = np.array(data)
        data = scaler.fit_transform(data)

        # Fit the transform
        reduction = umap.UMAP(
            n_components=self.parameters["components"],
            n_neighbors=self.parameters["neighbours"],
            min_dist=self.parameters["mindist"],
        )
        # TODO Dump the fit out as part of the proces
        data = reduction.fit_transform(data)

        dictionary_format_data = {}

        for key, value in zip(keys, data):
            dictionary_format_data[key] = value.tolist()

        write_json(self.output, dictionary_format_data)

    def run(self):
        staticproc(self.name, self.analyse)


class ExplodeAudio(FTISAnalyser):
    def __init__(self):
        super().__init__(parent_process)
        self.input_type = Ftypes.json
        self.output_type = Ftypes.folder

    def segment(self, workable):
        """Receives a full path to an audio file"""
        slices = self.slice_data[str(workable)]
        src = AudioSegment.from_file(workable, format="wav")
        sr = int(mediainfo(workable)["sample_rate"])

        for i, (start, end) in enumerate(zip(slices, slices[1:])):
            start = samps2ms(start, sr)
            end = samps2ms(end, sr)
            segment = src[start:end]
            segment.export(self.output / f"{i}_{workable.name}", format="wav")

    def run(self):
        self.slice_data = read_json(self.input)
        workables = [Path(x) for x in self.slice_data.keys()]
        multiproc(self.name, self.segment, workables)


class FluidLoudness(FTISAnalyser):
    def __init__(self):
        super().__init__(parent_process)
        self.input_type = Ftypes.folder
        self.output_type = Ftypes.json
        self.data_container = Manager().dict()

    def analyse(self, workable: str):
        loudness = fluid.loudness(
            workable,
            windowsize=self.parameters["windowsize"],
            hopsize=self.parameters["hopsize"],
            kweighting=self.parameters["kweighting"],
            truepeak=self.parameters["truepeak"],
        )

        self.data_container[str(workable)] = get_buffer(loudness)

    def run(self):
        workables = [x for x in self.input.iterdir() if x.suffix == ".wav"]
        multiproc(self.name, self.analyse, workables)
        write_json(self.output, dict(self.data_container))
        cleanup()


class FluidMFCC(FTISAnalyser):
    def __init__(self):
        super().__init__(parent_process)
        self.input_type = Ftypes.folder
        self.output_type = Ftypes.json
        self.data_container = Manager().dict()

    def analyse(self, workable):
        mfcc = fluid.mfcc(
            workable,
            fftsettings=self.parameters["fftsettings"],
            numbands=self.parameters["numbands"],
            numcoeffs=self.parameters["numcoeffs"],
        )
        self.data_container[str(workable)] = get_buffer(mfcc)

    def run(self):
        workables = [x for x in self.input.iterdir() if x.suffix == ".wav"]
        multiproc(self.name, self.analyse, workables)
        write_json(self.output, dict(self.data_container))
        # cleanup()


class FluidNoveltyslice(FTISAnalyser):
    def __init__(self):
        super().__init__(parent_process)
        self.input_type = Ftypes.folder
        self.output_type = Ftypes.json
        self.data_container = Manager().dict()

    def analyse(self, workable):
        noveltyslice = fluid.noveltyslice(
            workable,
            feature=self.parameters["feature"],
            fftsettings=self.parameters["fftsettings"],
            filtersize=self.parameters["filtersize"],
            minslicelength=self.parameters["minslicelength"],
            threshold=self.parameters["threshold"],
        )
        self.data_container[str(workable)] = get_buffer(noveltyslice)

    def run(self):
        workables = [x for x in self.input.iterdir() if x.suffix == ".wav"]
        multiproc(self.name, self.analyse, workables)
        write_json(self.output, dict(self.data_container))
        cleanup()


class FluidSines(FTISAnalyser):
    def __init__(self):
        super().__init__(parent_process)
        self.input_type = Ftypes.folder
        self.output_type = Ftypes.folder

    def analyse(self, workable):
        out_folder = self.output / workable.name
        out_folder.mkdir(exist_ok=True)

        sines = out_folder / f"sines_{workable.name}"
        residual = out_folder / f"residual_{workable.name}"

        fluid.sines(
            workable,
            sines=sines,
            residual=residual,
            bandwidth=self.parameters["bandwidth"],
            birthhighthreshold=self.parameters["birthhighthreshold"],
            birthlowthreshold=self.parameters["birthlowthreshold"],
            detectionthreshold=self.parameters["detectionthreshold"],
            fftsettings=self.parameters["fftsettings"],
            mintracklen=self.parameters["mintracklen"],
            trackingmethod=self.parameters["trackmethod"],
            trackfreqrange=self.parameters["trackfreqrange"],
            trackmagrange=self.parameters["trackmagrange"],
            trackprob=self.parameters["trackprob"],
        )

    def run(self):
        workables = [x for x in self.input.iterdir() if x.suffix == ".wav"]
        singleproc(self.name, self.analyse, workables)
        cleanup()


class FluidTransients(FTISAnalyser):
    def __init__(self):
        super().__init__(parent_process)
        self.input_type = Ftypes.folder
        self.output_type = Ftypes.folder

    def analyse(self, workable):
        out_folder = self.output / workable.name
        out_folder.mkdir(exist_ok=True)

        transients = out_folder / f"transients_{workable.name}"
        residual = out_folder / f"residual_{workable.name}"

        fluid.transients(
            workable,
            transients=transients,
            residual=residual,
            blocksize=self.parameters["blocksize"],
            clumplength=self.parameters["clumplength"],
            order=self.parameters["order"],
            padsize=self.parameters["padsize"],
            skew=self.parameters["skew"],
            threshback=self.parameters["threshback"],
            threshfwd=self.parameters["threshfwd"],
            windowsize=self.parameters["windowsize"],
        )

    def run(self):
        workables = [x for x in self.input.iterdir() if x.suffix == ".wav"]
        multiproc(self.name, self.analyse, workables)
        cleanup()


class HDBSClustering(FTISAnalyser):
    def __init__(self):
        super().__init__(config)
        self.input_type = Ftypes.json
        self.output_type = Ftypes.json

    def analyse(self):
        feature = read_json(self.input)
        keys = [x for x in feature.keys()]
        values = [x for x in feature.values()]

        data = np.array(values)

        db = hdbscan.HDBSCAN(
            min_cluster_size=self.parameters["minclustersize"],
            min_samples=self.parameters["minsamples"],
        ).fit(data)

        cluster_dict = {}

        for audio, cluster in zip(keys, db.labels_):
            if str(cluster) in cluster_dict:
                cluster_dict[str(cluster)].append(audio)
            else:
                cluster_dict[str(cluster)] = [audio]

        write_json(self.output, cluster_dict)

    def run(self):
        staticproc(self.name, self.analyse)


class AGCluster(FTISAnalyser):
    def __init__(self):
        self.input_type = Ftypes.json
        self.output_type = Ftypes.json

    def analyse(self):
        feature = read_json(self.input)
        keys = [x for x in feature.keys()]
        values = [x for x in feature.values()]

        data = np.array(values)

        db = AgglomerativeClustering(n_clusters=self.parameters["numclusters"]).fit(
            data
        )

        cluster_dict = {}

        for audio, cluster in zip(keys, db.labels_):
            if str(cluster) in cluster_dict:
                cluster_dict[str(cluster)].append(audio)
            else:
                cluster_dict[str(cluster)] = [audio]

        write_json(self.output, cluster_dict)

    def run(self):
        staticproc(self.name, self.analyse)
