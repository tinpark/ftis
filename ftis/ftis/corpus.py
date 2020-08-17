from pathlib import Path
from ftis.common.exceptions import(
    NoCorpusSource,
    InvalidSource
)
from ftis.common.analyser import FTISAnalyser
from ftis.common.proc import staticproc
from ftis.common.io import write_json, read_json

class Corpus:
    def __init__(self, 
        path="",
        file_type=[".wav", ".aiff", ".aif"]
    ):
        self.path = path
        self.file_type = file_type
        self.items = []
        self.get_items()

    def __add__(self, right):
        try:
            self.items += right.items # this is the fastest way to merge in place
        except AttributeError:
            raise 
        return self

    def get_items(self):
        if self.path == "":
            raise NoCorpusSource("Please provide a valid path for the corpus")
        
        self.path = Path(self.path).expanduser().resolve()

        if not self.path.exists():
            raise InvalidSource(self.path)

        self.items = [
            x 
            for x in self.path.iterdir() 
            if x.suffix in self.file_type
        ]

class Analysis:
    # TODO This could be merged directly into the corpus class where it would directly determine the type from the extension
    """This class lets you directly use analysis as an entry point to FTIS"""
    def __init__(self, path=""):
        self.path = path
        self.items = None
        self.get_items()
    
    def get_items(self):
        if self.path == "":
            raise NoCorpusSource("Please provide a valid path for the analysis")
        
        self.path = Path(self.path).expanduser().resolve()

        if not self.path.exists():
            raise InvalidSource(self.path)

        self.items = path

class PathLoader(FTISAnalyser):
    def __init__(self, 
        file_type=[".wav", ".aiff", ".aif"], 
        cache=False
    ):
        super().__init__(cache=cache)
        self.output = []
        self.file_type = file_type
        self.dump_type = ".json"

    def load_cache(self):
        d = read_json(self.dump_path)
        self.output = [Path(x) for x in d["corpus_items"]]

    def dump(self):
        d = {"corpus_items" : [str(x) for x in self.output]}
        write_json(self.dump_path, d)
    
    def collect_files(self):
        self.output = [x for x in self.input.iterdir() if x.suffix in self.file_type]

    def run(self):
        staticproc(self.name, self.collect_files)
