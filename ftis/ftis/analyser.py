import numpy as np
from ftis.common.analyser import FTISAnalyser
from ftis.common.io import write_json, read_json, peek
from ftis.common.proc import staticproc, multiproc, singleproc
from ftis.common.utils import create_hash, ignored_keys
from multiprocessing import Manager
from pathlib import Path
from flucoma.utils import get_buffer
from flucoma import fluid
from importlib import import_module
import librosa
from joblib import dump as jdump

class KDTree(FTISAnalyser):
    def __init__(self, cache=False):
        super().__init__(cache=cache)
        from sklearn.neighbors import KDTree as SKKDTree
    
    def dump(self):
        jdump(self.model, self.model_path)

    def analyse(self):
        data = [v for v in self.input.values()]
        keys = [k for k in self.input.keys()]

        data = np.array(data)
        self.model = SKKDTree(data)

    def run(self):
        singleproc(self.name, self.analyse)


class Stats(FTISAnalyser):
    """Get various statistics and derivatives of those"""
    def __init__(self, 
        numderivs=0, 
        flatten=True, 
        spec = [
            "mean", 
            "stddev", 
            "skewness", 
            "kurtosis", 
            "min", 
            "median", 
            "max"
        ],
        cache=False):

        super().__init__(cache=cache)
        self.numderivs = numderivs
        self.flatten = flatten
        self.spec = spec
        self.dump_type = ".json"
        from math import sqrt
        from scipy import stats

    def dump(self):
        write_json(self.dump_path, self.output)

    def load_cache(self):
        self.output = read_json(self.dump_path)

    @staticmethod
    def calc_stats(data, spec):
        
        describe = stats.describe(data)
        output = []
        if "mean" in spec:
            output.append(describe.mean)
        if "stddev" in spec:
            output.append(sqrt(describe.variance))
        if "skewness" in spec:
            output.append(describe.skewness)
        if "kurtosis" in spec:
            output.append(describe.kurtosis)
        if "minimum" in spec:
            output.append(describe.minmax[0])
        if "median" in spec:
            output.append(np.median(data))
        if "maximum" in spec:
            output.append(describe.minmax[1])
        return output

    def get_stats(self, base_data, num_derivs: int) -> list:
        """Given stats on n number derivatives from initial data"""
        container = []
        if num_derivs > 0:
            for i in range(num_derivs):
                deriv = np.diff(base_data, i + 1)
                container.append(self.calc_stats(deriv, self.spec))

        elif num_derivs <= 0:
            container = self.calc_stats(base_data, self.spec)

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

    def __init__(self, windowsize=1024, hopsize=512, cache=False):
        super().__init__(cache=cache)
        self.windowsize = windowsize
        self.hopsize = hopsize
        self.dump_type = ".json"
        from untwist import transforms, data

    def load_cache(self):
        self.output = read_json(self.dump_path)

    def dump(self):
        write_json(self.dump_path, self.output)

    def flux(self, workable):
        audio = data.Wave.read(str(workable))
        if audio.is_stereo():
            audio = np.sum(audio, axis=1)

        fft = transforms.STFT(fft_size=self.windowsize, hop_size=self.hopsize).process(
            audio
        )

        self.buffer[str(workable)] = list(
            np.sum(np.abs(np.diff(np.abs(fft))), axis=0)
        )  # Flux calculation here

    def run(self):
        self.buffer = Manager().dict()
        multiproc(self.name, self.flux, self.input)
        self.output = dict(self.buffer)


class Normalise(FTISAnalyser):
    def __init__(self, minimum=0, maximum=1, cache=False):
        super().__init__(cache=cache)
        self.min = minimum
        self.max = maximum
        self.dump_type = ".json"
        from sklearn.preprocessing import MinMaxScaler

    def load_cache(self):
        self.output = read_json(self.dump_path)

    def dump(self):
        write_json(self.dump_path, self.output)

    def analyse(self):
        scaled_data = MinMaxScaler((self.min, self.max)).fit_transform(self.features)

        self.output = {}
        for k, v in zip(self.keys, scaled_data):
            self.output[k] = list(v)

    def run(self):
        self.keys = [x for x in self.input.keys()]
        self.features = [x for x in self.input.values()]
        staticproc(self.name, self.analyse)


class Standardise(FTISAnalyser):
    def __init__(self, cache=False):
        super().__init__(cache=cache)
        self.dump_type = ".json"
        from sklearn.preprocessing import StandardScaler

    def load_cache(self):
        self.output = read_json(self.dump_path)

    def dump(self):
        jdump(self.model, self.model_dump)
        write_json(self.dump_path, self.output)

    def analyse(self):
        self.model = StandardScaler()
        self.model.fit(self.features)
        scaled_data = self.model.transform(self.features)
        self.output = {k: list(v) for k, v in zip(self.keys, scaled_data)}

    def run(self):
        self.keys = [x for x in self.input.keys()]
        self.features = [f for f in self.input.values()]
        staticproc(self.name, self.analyse)


class ClusteredSegmentation(FTISAnalyser):
    def __init__(self, numclusters=2, windowsize=4, cache=False):
        super().__init__(cache=cache)
        self.numclusters = numclusters
        self.windowsize = windowsize
        self.dump_type = ".json"
        from sklearn.cluster import AgglomerativeClustering

    def load_cache(self):
        self.output = read_json(self.dump_path)

    def dump(self):
        write_json(self.dump_path, self.output)

    def analyse(self, workable):
        slices = self.input[workable]
        slices = [int(x) for x in slices]
        if len(slices) == 1:
            self.buffer[workable] = slices
            return
        count = 0
        standardise = StandardScaler()
        model = AgglomerativeClustering(n_clusters=self.numclusters)

        while (count + self.windowsize) <= len(slices):
            indices = slices[
                count : count + self.windowsize
            ]  # create a section of the indices in question
            data = []
            for i, (start, end) in enumerate(zip(indices, indices[1:])):

                mfcc = mfcc(
                    workable,
                    fftsettings=[2048, -1, -1],
                    startframe=start,
                    numframes=end - start,
                )

                stats = get_buffer(stats(mfcc, numderivs=1), "numpy")

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
                        pass  # FIXME why are some indices erroring?
            count += 1
        self.buffer[workable] = slices

    def run(self):
        self.buffer = Manager().dict()
        workables = [x for x in self.input]
        singleproc(self.name, self.analyse, workables)
        self.output = dict(self.buffer)


class UMAP(FTISAnalyser):
    """Dimension reduction with UMAP algorithm"""
    def __init__(self, mindist=0.01, neighbours=7, components=2, cache=False):
        super().__init__(cache=cache)
        self.mindist = mindist
        self.neighbours = neighbours
        self.components = components
        self.output = {}
        self.dump_type = ".json"
        from umap import UMAP as umapdr

    def load_cache(self):
        self.output = read_json(self.dump_path)

    def dump(self):
        jdump(self.model, self.model_dump)
        write_json(self.dump_path, self.output)

    def analyse(self):
        data = [v for v in self.input.values()]
        keys = [k for k in self.input.keys()]

        data = np.array(data)

        self.model = umapdr(
            n_components=self.components,
            n_neighbors=self.neighbours,
            min_dist=self.mindist,
        )
        self.model.fit(data)
        transformed_data = self.model.transform(data)

        self.output = {k: v.tolist() for k, v in zip(keys, transformed_data)} 

    def run(self):
        staticproc(self.name, self.analyse)


class CollapseAudio(FTISAnalyser):
    def __init__(self):
        super().__init__()
        from scipy.io import wavfile

    def collapse(self, workable):
        out = self.outfolder / workable.name
        raw, sr = peek(workable)
        audio = None
        if raw.ndim == 1:
            audio = raw
        else:
            audio = raw.sum(axis=0) / raw.ndim
        wavfile.write(out, sr, audio)

    def run(self):
        self.outfolder = self.process.folder / f"{self.order}_{self.__class__.__name__}"
        self.outfolder.mkdir(exist_ok=True)
        workables = self.input
        self.output = [x for x in self.outfolder.iterdir() if x.suffix == ".wav"]
        singleproc(self.name, self.collapse, workables)


class ExplodeAudio(FTISAnalyser):
    def __init__(self, cache=False):
        super().__init__(cache=cache)
        self.dump_type = ".json"

    def segment(self, workable):
        # FIXME why do i need to mport here for it to not complain
        # FIXME Can maybe just move to the top if not a slow import
        from ftis.common.conversion import samps2ms
        from shutil import copyfile
        from pydub import AudioSegment
        from pydub.utils import mediainfo
        self.output_folder = self.process.folder / f"{self.order}_{self.__class__.__name__}"
        self.output_folder.mkdir(exist_ok=True)

        slices = self.input[str(workable)]

        if len(slices) == 1:
            copyfile(workable, self.output_folder / f"{workable.stem}_0.wav")

        src = AudioSegment.from_file(workable, format="wav")
        sr = int(mediainfo(workable)["sample_rate"])

        for i, (start, end) in enumerate(zip(slices, slices[1:])):
            start = samps2ms(start, sr)
            end = samps2ms(end, sr)
            segment = src[start:end]
            segment.export(self.output_folder / f"{workable.stem}_{i}.wav", format="wav")

    def load_cache(self):
        d = read_json(self.dump_path)
        self.output = [Path(x) for x in d["corpus_items"]]

    def dump(self):
        d = {"corpus_items" : [str(x) for x in self.output]}
        write_json(self.dump_path, d)

    def run(self):
        workables = [Path(x) for x in self.input.keys()]
        singleproc(self.name, self.segment, workables)
        self.output = [x for x in self.output_folder.iterdir() if x.suffix in ['.wav', '.aiff', '.aif']]


class FluidLoudness(FTISAnalyser):
    def __init__(self, windowsize=17640, hopsize=4410, kweighting=1, truepeak=1, cache=False):
        super().__init__(cache=cache)
        self.windowsize = windowsize
        self.hopsize = hopsize
        self.kweighting = kweighting
        self.truepeak = truepeak
        self.dump_type = ".json"

    def load_cache(self):
        self.output = read_json(self.dump_path)

    def dump(self):
        write_json(self.dump_path, self.output)

    def analyse(self, workable):
        hsh = create_hash(workable, self.identity)
        cache = self.process.cache / f"{hsh}.npy"

        if not cache.exists():
            loudness = get_buffer(
                fluid.loudness(workable,
                    windowsize=self.windowsize,
                    hopsize=self.hopsize,
                    kweighting=self.kweighting,
                    truepeak=self.truepeak
                ), "numpy"
            )
            np.save(cache, loudness)
        else:
            loudness = np.load(cache, allow_pickle=True)
        self.buffer[str(workable)] = loudness.tolist()

    def run(self):
        self.buffer = Manager().dict()
        workables = self.input
        multiproc(self.name, self.analyse, workables)
        self.output = dict(self.buffer)


class FluidMFCC(FTISAnalyser):
    def __init__(self,
        fftsettings=[1024, 512, 1024],
        numbands=40,
        numcoeffs=13,
        minfreq=80,
        maxfreq=20000,
        discard=False,
        cache=False
    ):
        super().__init__(cache=cache)
        self.fftsettings = fftsettings
        self.numbands = numbands
        self.numcoeffs = numcoeffs
        self.minfreq = minfreq
        self.maxfreq = maxfreq
        self.discard = discard
        self.dump_type = ".json"

    def load_cache(self):
        self.output = read_json(self.dump_path)

    def dump(self):
        write_json(self.dump_path, self.output)

    def analyse(self, workable):
        hsh = create_hash(workable, self.identity)
        cache = self.process.cache / f"{hsh}.npy"
        if cache.exists():
            print(cache)
            f = np.load(cache, allow_pickle=True)
        else:
            f = get_buffer(
                fluid.mfcc(
                    workable,
                    fftsettings=self.fftsettings,
                    numbands=self.numbands,
                    numcoeffs=self.numcoeffs,
                    minfreq=self.minfreq,
                    maxfreq=self.maxfreq,
                ), "numpy"
            )
            np.save(cache, f)
        if self.discard:
            self.buffer[str(workable)] = f.tolist()[1:]
        else:
            self.buffer[str(workable)] = f.tolist()

    def run(self):
        self.buffer = Manager().dict()
        multiproc(self.name, self.analyse, self.input)
        self.output = dict(self.buffer)


class LibroMFCC(FTISAnalyser):
    def __init__(
        self,
        numbands=40,
        numcoeffs=20,
        minfreq=80,
        maxfreq=20000,
        window=2048,
        hop=512,
        dct=2,
        discard=False,
        cache=False
    ):
        super().__init__(cache=cache)
        self.numbands = numbands
        self.numcoeffs = numcoeffs
        self.minfreq = minfreq
        self.maxfreq = maxfreq
        self.window = window
        self.hop = hop
        self.dct = dct
        self.discard = discard
        self.dump_type = ".json"

    def load_cache(self):
        self.output = read_json(self.dump_path)

    def dump(self):
        write_json(self.dump_path, self.output)

    def analyse(self, workable):
        hsh = create_hash(workable, self.identity)
        cache = self.process.cache / f"{hsh}.npy"
        if not cache.exists():
            y, sr = librosa.load(workable, sr=None, mono=True)
            feature = librosa.feature.mfcc(y=y, sr=sr,
                n_mfcc=self.numcoeffs,
                dct_type=self.dct,
                n_mels=self.numbands,
                fmax=self.maxfreq,
                fmin=self.minfreq,
                hop_length=self.hop,
                n_fft=self.window,
            )
            np.save(cache, feature)
        else:
            feature = np.load(cache, allow_pickle=True)

        if self.discard:
            self.buffer[str(workable)] = feature.tolist()[1:]
        else:
            self.buffer[str(workable)] = feature.tolist()

    def run(self):
        self.buffer = Manager().dict()
        singleproc(self.name, self.analyse, self.input)
        self.output = dict(self.buffer)


class LibroCQT(FTISAnalyser):
    def __init__(self,
        hop_length=512,
        minfreq=110,
        n_bins=84,
        bins_per_octave=12,
        tuning=0.0,
        filter_scale=1,
        norm=1,
        sparsity=0.01,
        window='hann',
        scale=True,
        pad_mode='reflect',
        cache=False
    ):
        super().__init__(cache=cache)
        self.hop_length = hop_length
        self.minfreq = minfreq
        self.n_bins = n_bins
        self.bins_per_octave = bins_per_octave
        self.tuning = tuning
        self.filter_scale = filter_scale
        self.norm = norm
        self.sparsity = sparsity
        self.window = window
        self.scale = scale
        self.pad_mode = pad_mode
        self.dump_type = ".json"

    def load_cache(self):
        self.output = read_json(self.dump_path)

    def dump(self):
        write_json(self.dump_path, self.output)

    def analyse(self, workable):
        y, sr = librosa.load(workable, sr=None, mono=True)
        cqt = librosa.cqt(y, sr, 
            fmin=self.minfreq,
            n_bins=self.n_bins,
            bins_per_octave=self.bins_per_octave,
            tuning=self.tuning,
            filter_scale=self.filter_scale,
            norm=self.norm,
            sparsity=self.sparsity,
            window=self.window,
            scale=self.scale,
            pad_mode=self.pad_mode
        )
        self.buffer[str(workable)] = np.abs(cqt).tolist()

    def run(self):
        self.buffer = Manager().dict()
        singleproc(self.name, self.analyse, self.input)
        self.output = dict(self.buffer)


class FluidNoveltyslice(FTISAnalyser):
    def __init__(
        self,
        feature=0,
        fftsettings=[1024, 512, 1024],
        filtersize=1,
        minslicelength=2048,
        threshold=0.5,
        cache=False
    ):
        super().__init__(cache=cache)
        self.feature = feature
        self.fftsettings = fftsettings
        self.filtersize = filtersize
        self.minslicelength = minslicelength
        self.threshold = threshold
        self.dump_type = ".json"

    def load_cache(self):
        self.output = read_json(self.dump_path)

    def dump(self):
        write_json(self.dump_path, self.output)

    def analyse(self, workable):
        noveltyslice = fluid.noveltyslice(
            workable,
            feature=self.feature,
            fftsettings=self.fftsettings,
            filtersize=self.filtersize,
            minslicelength=self.minslicelength,
            threshold=self.threshold,
        )

        self.buffer[str(workable)] = get_buffer(noveltyslice)

    def run(self):
        self.buffer = Manager().dict()
        multiproc(self.name, self.analyse, self.input)
        self.output = dict(self.buffer)


class FluidOnsetslice(FTISAnalyser):
    def __init__(
        self,
        fftsettings=[1024, 512, 1024],
        filtersize=5,
        framedelta=0,
        metric=0,
        minslicelength=2,
        threshold=0.5,
        cache=False
    ):
        super().__init__(cache=cache)
        self.fftsettings = fftsettings
        self.filtersize = filtersize
        self.framedelta = framedelta
        self.metric = metric
        self.minslicelength = minslicelength
        self.threshold = threshold
        self.dump_type = ".json"

    def load_cache(self):
        self.output = read_json(self.dump_path)

    def dump(self):
        write_json(self.dump_path, self.output)

    def analyse(self, workable):
        hsh = create_hash(workable, self.identity)
        cache = self.process.cache / f"{hsh}.wav"
        if not cache.exists():
            slice_output = get_buffer(
                fluid.onsetslice(workable,
                    indices=cache,
                    fftsettings=self.fftsettings,
                    filtersize=self.filtersize,
                    framedelta=self.framedelta,
                    metric=self.metric,
                    minslicelength=self.minslicelength,
                    threshold=self.threshold
                ), "numpy"
            )
        else:
            slice_output = get_buffer(cache, "numpy")

        self.buffer[str(workable)] = slice_output.tolist()

    def run(self):
        self.buffer = Manager().dict()
        workables = self.input
        singleproc(self.name, self.analyse, workables)
        self.output = dict(self.buffer)


class HDBSCluster(FTISAnalyser):
    def __init__(self, minclustersize=2, minsamples=1, cache=False):
        super().__init__(cache=cache)
        self.minclustersize = minclustersize
        self.minsamples = minsamples
        self.dump_type = ".json"
        from hdbscan import HDBSCAN

    def load_cache(self):
        self.output = read_json(self.dump_path)

    def dump(self):
        write_json(self.dump_path, self.output)

    def analyse(self):
        keys = [x for x in self.input.keys()]
        values = [x for x in self.input.values()]

        data = np.array(values)

        db = HDBSCAN(
            min_cluster_size=self.minclustersize, min_samples=self.minsamples,
        ).fit(data)

        self.output = {}

        for audio, cluster in zip(keys, db.labels_):
            if str(cluster) in self.output:
                self.output[str(cluster)].append(audio)
            else:
                self.output[str(cluster)] = [audio]

    def run(self):
        staticproc(self.name, self.analyse)


class AGCluster(FTISAnalyser):
    def __init__(self, numclusters=3, cache=False):
        super().__init__(cache=cache)
        self.numclusters = numclusters
        self.dump_type = ".json"

    def load_cache(self):
        self.output = read_json(self.dump_path)

    def dump(self):
        write_json(self.dump_path, self.output)

    def analyse(self):
        keys = [x for x in self.input.keys()]
        values = [x for x in self.input.values()]

        data = np.array(values)

        db = AgglomerativeClustering(n_clusters=self.numclusters).fit(data)

        self.output = {}

        for audio, cluster in zip(keys, db.labels_):
            if str(cluster) in self.output:
                self.output[str(cluster)].append(audio)
            else:
                self.output[str(cluster)] = [audio]

    def run(self):
        staticproc(self.name, self.analyse)


class ClusteredNMF(FTISAnalyser):
    def __init__(
        self,
        iterations=100,
        components=10,
        fftsettings=[4096, 1024, 4096],
        smoothing=11,
        polynomial=2,
        min_cluster_size=2,
        min_samples=2,
        cluster_selection_method="eom",
        cache=False
    ):
        super().__init__(cache=cache)
        self.components = components
        self.iterations = iterations
        self.fftsettings = fftsettings
        self.smoothing = smoothing
        self.polynomial = polynomial
        self.min_cluster_size = min_cluster_size
        self.min_samples = min_samples
        self.cluster_selection_method = cluster_selection_method
        self.dump_type = ".json"
        from scipy.signal import savgol_filter
        from scipy.io import wavfile

    def load_cache(self):
        self.output = read_json(self.dump_path)

    def dump(self):
        write_json(self.dump_path, self.output)

    def analyse(self, workable):
        nmf = fluid.nmf(
            workable,
            iterations=self.iterations,
            components=self.components,
            fftsettings=self.fftsettings,
        )
        bases = get_buffer(nmf.bases, "numpy")
        bases_smoothed = np.zeros_like(bases)

        for i, x in enumerate(bases):
            bases_smoothed[i] = savgol_filter(x, self.smoothing, self.polynomial)

        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=self.min_cluster_size,
            min_samples=self.min_samples,
            cluster_selection_method=self.cluster_selection_method,
        )

        cluster_labels = clusterer.fit_predict(bases_smoothed)
        unique_clusters = list(dict.fromkeys(cluster_labels))

        sound = get_buffer(nmf.resynth, "numpy")

        for x in unique_clusters:
            summed = np.zeros_like(sound[0])  # make an empty numpy array of same size
            base = workable.name
            output = self.output / f"{base}_{x}.wav"
            for idx, cluster in enumerate(cluster_labels):
                if cluster == x:
                    summed += sound[idx]
            wavfile.write(output, 44100, summed)

    def run(self):
        self.output = self.process.folder / f"{self.order}_{self.__class__.__name__}"
        self.output.mkdir(exist_ok=True)
        workables = [
            k
            for k in self.input.iterdir()
            if k.name != ".DS_Store" and k.is_file() and k.suffix == ".wav"
        ]
        singleproc(self.name, self.analyse, workables)


# class FluidSines(FTISAnalyser):
#     def __init__(self,
#     bandwidth=76,
#     birthhighthreshold=-60,
#     birthlowthreshold=-24,
#     detectionthreshold=-96,
#     fftsettings=[1024, 512, 1024],
#     mintracklen=15,
#     trackingmethod=0,
#     trackfreqrange=50.0,
#     trackmagrange=15.0,
#     trackprob=0.5
#     ):
#         super().__init__()
#         self.bandwidth = bandwidth,
#         self.birthhighthreshold,
#         self.birthlowthreshold,
#         self.detectionthreshold,
#         self.fftsettings,
#         self.mintracklen

#     def analyse(self, workable):
#         out_folder = self.output / workable.name
#         out_folder.mkdir(exist_ok=True)

#         sines = out_folder / f"sines_{workable.name}"
#         residual = out_folder / f"residual_{workable.name}"

#         fluid.sines(
#             workable,
#             sines=sines,
#             residual=residual,
#             bandwidth=self.parameters["bandwidth"],
#             birthhighthreshold=self.parameters["birthhighthreshold"],
#             birthlowthreshold=self.parameters["birthlowthreshold"],
#             detectionthreshold=self.parameters["detectionthreshold"],
#             fftsettings=self.parameters["fftsettings"],
#             mintracklen=self.parameters["mintracklen"],
#             trackingmethod=self.parameters["trackmethod"],
#             trackfreqrange=self.parameters["trackfreqrange"],
#             trackmagrange=self.parameters["trackmagrange"],
#             trackprob=self.parameters["trackprob"],
#         )

#     def run(self):
#         workables = self.input
#         singleproc(self.name, self.analyse, workables)
#         self.output

# class FluidTransients(FTISAnalyser):
#     def __init__(self):
#         super().__init__(parent_process)
#         self.input_type = Ftypes.folder
#         self.output_type = Ftypes.folder

#     def analyse(self, workable):
#         out_folder = self.output / workable.name
#         out_folder.mkdir(exist_ok=True)

#         transients = out_folder / f"transients_{workable.name}"
#         residual = out_folder / f"residual_{workable.name}"

#         fluid.transients(
#             workable,
#             transients=transients,
#             residual=residual,
#             blocksize=self.parameters["blocksize"],
#             clumplength=self.parameters["clumplength"],
#             order=self.parameters["order"],
#             padsize=self.parameters["padsize"],
#             skew=self.parameters["skew"],
#             threshback=self.parameters["threshback"],
#             threshfwd=self.parameters["threshfwd"],
#             windowsize=self.parameters["windowsize"],
#         )

#     def run(self):
#         workables = self.input
#         multiproc(self.name, self.analyse, workables)
#         cleanup()
