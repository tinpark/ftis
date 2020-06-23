import os
import yaml
import math
import soundfile as sf
import simpleaudio as sa
from importlib import import_module
from pathlib import Path

# JSON importing
try:
    import rapidjson as rj
except ImportError:
    import json as rj


def nextpow(x):
    """Find the next power of 2 from x"""
    return 2 ** math.ceil(math.log(x)/math.log(2))

def get_workables(pth):
    temp_workables = []
    for root, _, files in os.walk(pth):
        for f in files:
            full_path = Path(root) / f
            temp_workables.append(full_path)
    return temp_workables

def filter_extensions(workables, valid_ext):
    """Filters path objects from a list based on extension"""
    return [x for x in workables if x.suffix in valid_ext]
    
def expand_tilde(path: str) -> str:
    """Expand tilde to user home folder"""
    if path[0] == "~":
        return os.path.expanduser(path)
    else:
        return path

def import_analyser(class_name: str):
    path = f"ftis.analysers.{class_name}"
    module = import_module(path)
    return module.main


def lines_to_list(input_file: str) -> list:
    """Take the lines of a file and return it as a list"""
    with open(input_file, "r") as f:
        lines = f.readlines(0)
        content = [x.strip() for x in lines]
        return content


def check_make(dir_path: str):
    """Create a directory if it doesn't exist"""
    try:
        os.mkdir(dir_path)
    except FileExistsError:
        pass


def read_yaml(yaml_file):
    with open(yaml_file, "r") as stream:
        try:
            return yaml.safe_load(stream)
        except yaml.YAMLError as exc:
            print(exc)


def list_to_coll(list_input: list, out_file: str):
    """Turns a list into a coll."""
    f = open(out_file, "w+")
    counter = 0
    for item in list_input:
        f.write(f"{counter}, {item};")
        counter += 1
    f.close()


def wipe_dir(dir: str):
    """Wipe a directory given a path"""
    for file_name in os.listdir(dir):
        os.remove(os.path.join(dir, file_name))


def bytes_to_mb(val: int) -> float:
    """convert bytes to mb"""
    return val * 0.000001


def samps2ms(samples: float, sr: int) -> float:
    """
    convert samples to milliseconds given a sampling rate
    """
    return (samples / sr) * 1000.0


def ms2samps(ms: int, sr: int) -> int:
    """
    convert milliseconds to samples given a sample rate
    """
    return (ms * 0.001) * sr


def rm_ds(file_list: list) -> list:
    """
    Remove .DS_Store if in a list
    """
    if ".DS_Store" in file_list:
        file_list.remove(".DS_Store")
    return file_list


def bufspill(audio_file_path: str):
    """Returns an audio files fp32 values as a flat numpy array"""
    data, sr = sf.read(audio_file_path)
    data = data.transpose()
    return (data, sr)


def write_json(json_file_path: str, in_dict: dict):
    """Takes a dictionary and writes it to JSON file"""
    with open(json_file_path, "w+") as fp:
        rj.dump(in_dict, fp, indent=4)


def read_json(json_file_path: str) -> dict:
    """Takes a JSON file and returns a dictionary"""
    with open(json_file_path, "r") as fp:
        data = rj.load(fp)
        return data


def walkman(audio_path: str):
    """Play a sound file given a path to a valid piece of audio"""
    wave_obj = sa.WaveObject.from_wave_file(os.path.join(audio_path))
    play_obj = wave_obj.play()
    play_obj.wait_done()
